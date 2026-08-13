#!/usr/bin/env python3
"""Monotonic campaign state, CAS mutation, locks, and budget accounting."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import copy
import fcntl
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from _model_evolution_campaign import validate_campaign
from _model_evolution_contract import (
    BUDGET_FIELDS,
    ContractError,
    SKILL_IDS,
    canonical_bytes,
)


PHASES = (
    "declared",
    "apparatus_ready",
    "target_profile_ready",
    "calibration_ready",
    "current_evidence_ready",
    "decision_ready",
    "candidate_registered",
    "candidate_evidence_ready",
    "final_plugin_ready",
    "holdout_ready",
)
ALLOWED_PHASE_TRANSITIONS = {
    phase: {phase, PHASES[index + 1]} if index + 1 < len(PHASES) else {phase}
    for index, phase in enumerate(PHASES)
}
ALLOWED_PHASE_TRANSITIONS["decision_ready"].add("final_plugin_ready")
ALLOWED_PHASE_TRANSITIONS["calibration_ready"].add("decision_ready")
NEXT_EVENT = {
    "declared": "preflight",
    "apparatus_ready": "probe",
    "target_profile_ready": "record grader_calibration or register-plan target_current",
    "calibration_ready": "register-plan target_current",
    "current_evidence_ready": "record transition_report",
    "decision_ready": (
        "register-plan target_prior, record revision_report, candidate_source, "
        "or plugin_build"
    ),
    "candidate_registered": "register-plan target_candidate",
    "candidate_evidence_ready": "record plugin_build",
    "final_plugin_ready": "register-plan target_holdout",
    "holdout_ready": "qualify",
}


class StateError(ValueError):
    """A campaign state, transition, or concurrency failure."""


def zero_counts(*, unknown_observed: bool = False) -> dict[str, int | None]:
    return {
        field: None if unknown_observed and field in {"artifact_bytes"} else 0
        for field in BUDGET_FIELDS
    }


def phase_at_least(current: str, target: str) -> bool:
    try:
        return PHASES.index(current) >= PHASES.index(target)
    except ValueError as exc:
        raise StateError("campaign phase is unknown") from exc


def validate_transition(previous: str, current: str) -> None:
    if previous not in ALLOWED_PHASE_TRANSITIONS or current not in PHASES:
        exc = ValueError(current)
        raise StateError("campaign phase is unknown") from exc
    if current not in ALLOWED_PHASE_TRANSITIONS[previous]:
        raise StateError(f"illegal campaign phase transition: {previous} -> {current}")


def reserve_budget(state: dict[str, Any], increments: dict[str, int]) -> None:
    if set(increments) - set(BUDGET_FIELDS):
        raise StateError("budget reservation contains an unknown field")
    ceiling = state["budgets"]["ceiling"]
    reserved = state["budgets"]["reserved"]
    for field, amount in increments.items():
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise StateError("budget reservation must be a non-negative integer")
        if ceiling[field] is None or reserved[field] is None:
            raise StateError(f"budget field {field} is not reservable")
        if reserved[field] + amount > ceiling[field]:
            raise StateError(f"budget ceiling exceeded for {field}")
    for field, amount in increments.items():
        reserved[field] += amount


def record_observed_budget(
    state: dict[str, Any], observed: dict[str, int | None]
) -> None:
    if set(observed) - set(BUDGET_FIELDS):
        raise StateError("observed budget contains an unknown field")
    target = state["budgets"]["observed"]
    for field, amount in observed.items():
        if amount is not None and (
            isinstance(amount, bool) or not isinstance(amount, int) or amount < 0
        ):
            raise StateError("observed budget must be non-negative or null")
        target[field] = amount


def advance_preflight(state: dict[str, Any], report_binding: dict[str, Any]) -> None:
    if state["phase"] != "declared":
        raise StateError("preflight is only legal from declared")
    if state["apparatus_report"] is not None:
        raise StateError("apparatus report is already recorded")
    state["apparatus_report"] = report_binding
    state["phase"] = "apparatus_ready"


def reserve_probes(state: dict[str, Any], probe_ids: list[str]) -> None:
    if state["phase"] != "apparatus_ready":
        raise StateError("probe is only legal after apparatus preflight")
    existing = state["interaction_probes"]["requests"]
    if existing:
        if any(item["status"] == "reserved" for item in existing):
            raise StateError("partial probe reservation is not retryable")
        raise StateError("probe requests are already frozen")
    if not probe_ids or len(probe_ids) > 6 or len(set(probe_ids)) != len(probe_ids):
        raise StateError("probe request set is empty, duplicated, or exceeds six")
    reserve_budget(state, {"provider_requests": len(probe_ids)})
    prefix = f"{state['campaign_id']}.{state['state_revision']}"
    if len(prefix) > 116:
        raise StateError("campaign ID is too long for probe request IDs")
    state["interaction_probes"]["requests"] = [
        {
            "request_id": f"probe.{prefix}.{index:02d}",
            "probe_id": probe_id,
            "status": "reserved",
            "artifact": None,
            "result_status": None,
        }
        for index, probe_id in enumerate(probe_ids, 1)
    ]


def close_probes(
    state: dict[str, Any],
    *,
    artifacts: dict[str, dict[str, Any]],
    statuses: dict[str, str],
    results_binding: dict[str, Any],
    observed_host_binding: dict[str, Any],
    blocker: str | None = None,
) -> None:
    requests = state["interaction_probes"]["requests"]
    if state["phase"] != "apparatus_ready" or not requests:
        raise StateError("probe closure has no matching reservation")
    if any(item["status"] != "reserved" for item in requests):
        raise StateError("probe reservation is not uniformly open")
    if blocker is not None and not blocker.strip():
        raise StateError("probe blocker is empty")
    request_ids = {item["request_id"] for item in requests}
    if set(artifacts) != request_ids or set(statuses) != request_ids:
        raise StateError("probe terminal set differs from reservation")
    for item in requests:
        request_id = item["request_id"]
        item.update(
            {
                "status": "closed",
                "artifact": artifacts[request_id],
                "result_status": statuses[request_id],
            }
        )
    state["interaction_probes"]["results"] = results_binding
    state["interaction_probes"]["blocker"] = (
        blocker.strip()[:512] if blocker is not None else None
    )
    state["profiles"]["target_observed"] = observed_host_binding
    previous_requests = state["budgets"]["observed"]["provider_requests"]
    state["budgets"]["observed"]["provider_requests"] = (
        None if previous_requests is None else previous_requests + len(requests)
    )
    state["phase"] = "apparatus_ready" if blocker is not None else "target_profile_ready"


def block_probes(state: dict[str, Any], reason: str) -> None:
    requests = state["interaction_probes"]["requests"]
    if state["phase"] != "apparatus_ready" or not requests:
        raise StateError("probe blocker has no matching reservation")
    if not reason.strip():
        raise StateError("probe blocker reason is empty")
    state["interaction_probes"]["blocker"] = reason.strip()[:512]
    state["budgets"]["observed"]["provider_requests"] = None


def register_plan(
    state: dict[str, Any],
    plan_record: dict[str, Any],
) -> None:
    role = plan_record["role"]
    required_phase = {
        "target_current": {"target_profile_ready", "calibration_ready"},
        "target_candidate": {"candidate_registered"},
        "target_prior": {"decision_ready"},
        "target_holdout": {"final_plugin_ready"},
    }[role]
    if state["phase"] not in required_phase:
        raise StateError(f"{role} plan is not legal from {state['phase']}")
    if any(
        item["role"] == role and item["skill_id"] == plan_record["skill_id"]
        for item in state["plans"]
    ):
        raise StateError("plan role and Skill are already registered")
    if role == "target_prior" and (
        state["candidate"] is not None
        or state["profiles"]["predecessor"] is not None
    ):
        raise StateError("target_prior is only legal for candidate-null bootstrap")
    if role == "target_current" and plan_record["model_grade_ceiling"]:
        if state["phase"] != "calibration_ready":
            raise StateError("model-graded current plan requires all calibrations")
        if state["skill_evidence"][plan_record["skill_id"]][
            "grader_calibration"
        ] is None:
            raise StateError("model-graded current plan requires calibration")
    reserve_budget(
        state,
        {
            "execute": plan_record["execute_ceiling"],
            "model_grade": plan_record["model_grade_ceiling"],
            "provider_requests": (
                plan_record["execute_ceiling"] + plan_record["model_grade_ceiling"]
            ),
        },
    )
    state["plans"].append(plan_record)
    state["plans"].sort(key=lambda item: (item["role"], item["skill_id"]))
    if role == "target_current" and state["phase"] == "target_profile_ready":
        state["phase"] = "calibration_ready"


def _has_plan(state: dict[str, Any], role: str, skill_id: str) -> bool:
    return any(
        item["role"] == role and item["skill_id"] == skill_id for item in state["plans"]
    )


def record_evidence(
    state: dict[str, Any],
    *,
    role: str,
    binding: dict[str, Any],
    skill_id: str | None,
) -> None:
    if role == "grader_calibration":
        if (
            state["phase"] != "target_profile_ready"
            or skill_id not in SKILL_IDS
        ):
            raise StateError("grader calibration is not legal from the current phase")
        evidence = state["skill_evidence"][skill_id]
        if evidence["grader_calibration"] is not None:
            raise StateError("grader calibration is already recorded")
        evidence["grader_calibration"] = binding
        if all(
            state["skill_evidence"][selected]["grader_calibration"] is not None
            for selected in SKILL_IDS
        ):
            state["phase"] = "calibration_ready"
        return
    if role == "plugin_build":
        if skill_id is not None or state["skill_evidence"]["plugin_build"] is not None:
            raise StateError("plugin build identity or cardinality is invalid")
        if (
            state["phase"] == "decision_ready"
            and state["candidate"] is None
            and all(
                state["skill_evidence"][item]["revision_report"] is not None
                for item in SKILL_IDS
            )
        ):
            state["skill_evidence"]["plugin_build"] = binding
            state["phase"] = "final_plugin_ready"
            return
        if (
            state["phase"] == "candidate_evidence_ready"
            and state["candidate"] is not None
        ):
            state["skill_evidence"]["plugin_build"] = binding
            state["phase"] = "final_plugin_ready"
            return
        raise StateError("plugin build is not legal from the current phase")
    if skill_id is None or skill_id not in state["skill_evidence"]:
        raise StateError("Skill-scoped evidence requires an exact Skill ID")
    field_role = {
        "current_summary": ("current_summary", "target_current", {"calibration_ready"}),
        "transition_report": (
            "transition_report",
            None,
            {"current_evidence_ready"},
        ),
        "candidate_summary": (
            "candidate_summary",
            "target_candidate",
            {"candidate_registered"},
        ),
        "revision_report": (
            "revision_report",
            None,
            {"candidate_registered", "decision_ready"},
        ),
        "holdout_summary": (
            "holdout_summary",
            "target_holdout",
            {"final_plugin_ready"},
        ),
    }
    try:
        field, required_plan, allowed_phases = field_role[role]
    except KeyError as exc:
        raise StateError(f"unsupported evidence role: {role}") from exc
    if role == "revision_report" and state["phase"] == "decision_ready" and (
        state["candidate"] is not None or state["profiles"]["predecessor"] is not None
    ):
        raise StateError("decision-ready revision is only legal for candidate-null bootstrap")
    if state["phase"] not in allowed_phases:
        raise StateError(f"{role} is not legal from {state['phase']}")
    if required_plan is not None and not _has_plan(state, required_plan, skill_id):
        raise StateError(f"{role} lacks a registered {required_plan} plan")
    if state["skill_evidence"][skill_id][field] is not None:
        raise StateError(f"{role} is already recorded for {skill_id}")
    state["skill_evidence"][skill_id][field] = binding
    if role == "current_summary" and all(
        state["skill_evidence"][item]["current_summary"] is not None
        for item in SKILL_IDS
    ):
        state["phase"] = (
            "decision_ready"
            if state["profiles"]["predecessor"] is None
            else "current_evidence_ready"
        )
    elif role == "transition_report" and all(
        state["skill_evidence"][item]["transition_report"] is not None
        for item in SKILL_IDS
    ):
        state["phase"] = "decision_ready"
    elif (
        state["candidate"] is not None
        and role in {"candidate_summary", "revision_report"}
        and all(
            state["skill_evidence"][item]["candidate_summary"] is not None
            and state["skill_evidence"][item]["revision_report"] is not None
            for item in SKILL_IDS
        )
    ):
        state["phase"] = "candidate_evidence_ready"
    elif role == "holdout_summary" and all(
        state["skill_evidence"][item]["holdout_summary"] is not None
        for item in SKILL_IDS
    ):
        state["phase"] = "holdout_ready"


def accept_candidate(state: dict[str, Any], candidate: dict[str, Any]) -> None:
    if state["phase"] != "decision_ready":
        raise StateError("candidate is only legal from decision_ready")
    if state["candidate"] is not None or state["budgets"]["candidate_count"] != 0:
        raise StateError("campaign already owns a candidate")
    reserve_budget(state, {"candidates": 1})
    state["candidate"] = candidate
    state["budgets"]["candidate_count"] = 1
    state["phase"] = "candidate_registered"


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def create_no_overwrite(path: Path, value: dict[str, Any]) -> None:
    payload = canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise StateError(f"refusing to replace existing state: {path.name}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def publish_qualification(
    campaign_root: Path,
    qualification: dict[str, Any],
    markdown: str,
    *,
    expected_revision: int,
) -> Path:
    target = campaign_root / "qualification"
    if target.exists() or target.is_symlink():
        raise StateError("qualification directory already exists")
    temporary = campaign_root / f".qualification.tmp-{expected_revision}"
    if temporary.is_symlink():
        raise StateError("qualification orphan is a symlink")
    if temporary.exists():
        if not temporary.is_dir():
            raise StateError("qualification orphan is not a directory")
        shutil.rmtree(temporary)
    temporary.mkdir(mode=0o700)
    try:
        with (temporary / "qualification.json").open("xb") as handle:
            handle.write(canonical_bytes(qualification) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        with (temporary / "qualification.md").open("xb") as handle:
            handle.write(markdown.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, target)
        directory = os.open(campaign_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise
    return target


class CampaignStore:
    def __init__(
        self,
        campaign_root: Path,
        repository_root: Path,
    ):
        self.root = campaign_root.resolve()
        self.repository_root = repository_root.resolve(strict=True)
        self.path = self.root / "campaign.json"
        self.lock_path = self.root / ".campaign.lock"
        self.probe_lock_path = self.root / ".probe.operation.lock"

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("campaign state is missing or invalid JSON") from exc
        try:
            validate_campaign(value)
        except ContractError as exc:
            raise StateError(str(exc)) from exc
        return value

    def read(self) -> dict[str, Any]:
        """Read-only state access: no lock, temp file, or timestamp mutation."""
        return self._read()

    def create(
        self,
        value: dict[str, Any],
        *,
        bootstrap_paths: tuple[Path, ...] = (),
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        allowed_nodes: set[Path] = set()
        for candidate in bootstrap_paths:
            if candidate.is_symlink() or not candidate.is_file():
                raise StateError("campaign bootstrap input must be a regular file")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(self.root):
                raise StateError("campaign bootstrap input is outside campaign root")
            allowed_nodes.add(resolved)
            allowed_nodes.update(
                parent
                for parent in resolved.parents
                if parent != self.root and parent.is_relative_to(self.root)
            )
        existing_nodes = set(self.root.rglob("*"))
        if any(path.is_symlink() for path in existing_nodes):
            raise StateError("campaign bootstrap input cannot be a symlink")
        if existing_nodes != allowed_nodes:
            raise StateError("campaign directory contains undeclared bootstrap content")
        try:
            validate_campaign(value)
        except ContractError as exc:
            raise StateError(str(exc)) from exc
        create_no_overwrite(self.path, value)
        try:
            self.lock_path.touch(mode=0o600, exist_ok=False)
            self.probe_lock_path.touch(mode=0o600, exist_ok=False)
        except BaseException:
            self.probe_lock_path.unlink(missing_ok=True)
            self.lock_path.unlink(missing_ok=True)
            self.path.unlink(missing_ok=True)
            raise

    @contextmanager
    def hold_probe_operation(self) -> Iterator[None]:
        try:
            lock_handle = self.probe_lock_path.open("r+b")
        except OSError as exc:
            raise StateError("probe operation lock is unavailable") from exc
        with lock_handle:
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StateError("probe operation is already running") from exc
            yield

    def probe_operation_running(self) -> bool:
        try:
            lock_handle = self.probe_lock_path.open("r+b")
        except OSError as exc:
            raise StateError("probe operation lock is unavailable") from exc
        with lock_handle:
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False

    def mutate(
        self,
        expected_revision: int,
        operation: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        if isinstance(expected_revision, bool) or expected_revision < 0:
            raise StateError("expected revision must be a non-negative integer")
        try:
            lock_handle = self.lock_path.open("r+b")
        except OSError as exc:
            raise StateError("campaign lock file is unavailable") from exc
        with lock_handle:
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StateError("campaign mutation lock is held") from exc
            qualification_root = self.root / "qualification"
            if qualification_root.exists() or qualification_root.is_symlink():
                raise StateError("qualified campaign is immutable")
            current = self._read()
            if current["state_revision"] != expected_revision:
                raise StateError(
                    f"stale expected revision {expected_revision}; current is {current['state_revision']}"
                )
            updated = copy.deepcopy(current)
            operation(updated)
            validate_transition(current["phase"], updated["phase"])
            updated["state_revision"] = expected_revision + 1
            try:
                validate_campaign(updated)
            except ContractError as exc:
                raise StateError(str(exc)) from exc
            _atomic_bytes(self.path, canonical_bytes(updated) + b"\n")
            return updated

    def publish_qualification(
        self,
        expected_revision: int,
        projector: Callable[[dict[str, Any]], tuple[dict[str, Any], str]],
    ) -> tuple[dict[str, Any], Path]:
        try:
            lock_handle = self.lock_path.open("r+b")
        except OSError as exc:
            raise StateError("campaign lock file is unavailable") from exc
        with lock_handle:
            try:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StateError("campaign mutation lock is held") from exc
            current = self._read()
            if current["state_revision"] != expected_revision:
                raise StateError(
                    f"stale expected revision {expected_revision}; current is "
                    f"{current['state_revision']}"
                )
            qualification, markdown = projector(copy.deepcopy(current))
            target = publish_qualification(
                self.root,
                qualification,
                markdown,
                expected_revision=expected_revision,
            )
            return current, target


def status_projection(
    state: dict[str, Any],
    *,
    plan_statuses: list[dict[str, Any]],
    blockers: list[dict[str, str]],
    runner_commands: list[str],
    probe_running: bool,
    probe_command: str | None,
) -> dict[str, Any]:
    plan_blockers = [
        {
            "code": "plan-invalid",
            "message": (
                f"{item.get('role', 'unknown')}/{item.get('skill_id', 'unknown')} "
                f"has {item['invalid_attempts']} invalid attempt(s)"
            ),
        }
        for item in plan_statuses
        if item.get("invalid_attempts", 0)
        and not item.get("recoverable_attempts", [])
    ]
    effective_blockers = [*blockers, *plan_blockers]
    skills = {
        skill_id: {
            field: binding is not None
            for field, binding in state["skill_evidence"][skill_id].items()
        }
        for skill_id in SKILL_IDS
    }
    active = sum(len(item.get("active_attempts", [])) for item in plan_statuses)
    recoverable = sum(
        len(item.get("recoverable_attempts", [])) for item in plan_statuses
    )
    if effective_blockers:
        next_event = None
    elif probe_running:
        next_event = "monitor interaction probes"
    elif probe_command is not None:
        next_event = "run interaction probes"
    else:
        next_event = NEXT_EVENT[state["phase"]]
    return {
        "schema_version": "model-evolution-status/1",
        "campaign_id": state["campaign_id"],
        "state_revision": state["state_revision"],
        "phase": state["phase"],
        "skills": skills,
        "plan_statuses": plan_statuses,
        "active_attempts": active,
        "recoverable_attempts": recoverable,
        "budget": state["budgets"],
        "probe_running": probe_running,
        "probe_command": None if effective_blockers else probe_command,
        "next_event": next_event,
        "runner_commands": [] if effective_blockers else runner_commands,
        "blockers": effective_blockers,
    }
