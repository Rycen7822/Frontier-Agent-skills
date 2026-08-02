"""Shared data builders for controller tests; contains no test oracle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import artifacts, campaign, host, reports, source_proof, studies


def hash_value(digit: str = "1") -> str:
    return f"sha256:{digit * 64}"


HASH = hash_value()


def request_entry(
    request_id: str,
    *,
    request_kind: str = "execute",
    study: str = "study-01",
    family: str = "scored",
    subject_id: str = "subject-01",
    attempt_index: int = 0,
    predecessor_request_id: str | None = None,
    activation: str | dict = "required",
) -> dict:
    reviewer = family == "reviewer_calibration"
    return {
        "request_id": request_id,
        "stage": "r1-controller",
        "study": study,
        "family": family,
        "request_kind": request_kind,
        "subject_id": subject_id,
        "arm": "candidate",
        "input_binding_hash": hash_value("1"),
        "output_schema_hash": (
            None if request_kind == "execute" else hash_value("2")
        ),
        "requested_model": "gpt-5.6-sol" if reviewer else "gpt-5.6-luna",
        "requested_reasoning_effort": "max" if reviewer else "high",
        "requested_service_tier": "priority",
        "attempt_index": attempt_index,
        "predecessor_request_id": predecessor_request_id,
        "activation": activation,
    }


def initialize_existing(root: Path) -> dict:
    return campaign.initialize_attempt(
        root,
        attempt_id="attempt-01",
        campaign_id="campaign-01",
        plan_sha256=hash_value("1"),
        candidate_revision="2" * 40,
        candidate_source_tree_hash=hash_value("3"),
        candidate_plugin_tree_hash=hash_value("4"),
        controller_content_hash=hash_value("5"),
        evaluator_source_hash=hash_value("6"),
        phase_contract_path=root / "phase-contract.json",
        request_manifest_path=root / "request-manifest.json",
        stage="r1-controller",
        continuation_token="continue-once",
    )


def initialize(
    root: Path,
    *,
    required: list[dict] | None = None,
    conditional: list[dict] | None = None,
) -> dict:
    root.mkdir()
    campaign.write_request_manifest(
        root / "request-manifest.json",
        campaign_id="campaign-01",
        required_requests=required or [request_entry("request-1")],
        conditional_requests=conditional or [],
    )
    (root / "phase-contract.json").write_text(
        '{"schema_version":"test-phase-contract/1.0"}\n',
        encoding="utf-8",
    )
    return initialize_existing(root)


def receipt(
    root: Path,
    request_id: str,
    *,
    terminal_status: str = "completed",
    failure_class: str | None = None,
) -> dict:
    entry = campaign.request_entry(root, request_id)
    value = {
        "request_id": request_id,
        "entry_hash": artifacts.canonical_hash(entry),
        "input_binding_hash": entry["input_binding_hash"],
        "output_schema_hash": entry["output_schema_hash"],
        "terminal_status": terminal_status,
        "failure_class": failure_class,
    }
    return {**value, "receipt_hash": artifacts.canonical_hash(value)}


def reserve(
    root: Path,
    request_id: str,
    receipts: list[dict] | None = None,
) -> dict:
    entry = campaign.request_entry(root, request_id)
    return campaign.reserve_provider_request(
        root,
        request_id=request_id,
        entry_hash=artifacts.canonical_hash(entry),
        native_receipts=receipts,
    )


def _schema(
    *,
    required: tuple[str, ...] = (),
    properties: tuple[str, ...] = (),
    definitions: dict | None = None,
) -> dict:
    value = {
        "required": list(required),
        "properties": {name: {} for name in properties},
    }
    if not required:
        value.pop("required")
    if definitions:
        value["definitions"] = definitions
    return value


def app_server_schema_tree(root: Path) -> None:
    schema_root = root / "v2"
    schema_root.mkdir()
    thread_item = {
        "oneOf": [
            {
                "required": ["id", "text", "type"],
                "properties": {"type": {"enum": ["agentMessage"]}},
            },
            {
                "required": ["command", "id", "status", "type"],
                "properties": {"type": {"enum": ["commandExecution"]}},
            },
        ],
    }
    user_input = {
        "oneOf": [
            {
                "required": ["text", "type"],
                "properties": {"type": {"enum": ["text"]}},
            },
            {
                "required": ["name", "path", "type"],
                "properties": {"type": {"enum": ["skill"]}},
            },
        ],
    }
    documents = {
        "ThreadStartParams.json": _schema(properties=(
            "approvalPolicy",
            "cwd",
            "ephemeral",
            "experimentalRawEvents",
            "model",
            "sandbox",
            "serviceTier",
        )),
        "TurnStartParams.json": _schema(
            required=("input", "threadId"),
            properties=(
                "approvalPolicy",
                "cwd",
                "effort",
                "input",
                "model",
                "outputSchema",
                "sandboxPolicy",
                "serviceTier",
                "threadId",
            ),
            definitions={"UserInput": user_input},
        ),
        "ThreadStartResponse.json": _schema(
            required=("thread",),
            properties=("thread",),
        ),
        "TurnStartResponse.json": _schema(
            required=("turn",),
            properties=("turn",),
        ),
        "TurnCompletedNotification.json": _schema(
            required=("threadId", "turn"),
            properties=("threadId", "turn"),
        ),
        "ItemCompletedNotification.json": _schema(
            required=("item", "threadId", "turnId"),
            properties=("item", "threadId", "turnId"),
            definitions={"ThreadItem": thread_item},
        ),
        "ThreadTokenUsageUpdatedNotification.json": _schema(
            required=("threadId", "tokenUsage", "turnId"),
            properties=("threadId", "tokenUsage", "turnId"),
            definitions={
                "ThreadTokenUsage": _schema(
                    required=("last", "total"),
                    properties=("last", "total"),
                ),
            },
        ),
        "ModelSafetyBufferingUpdatedNotification.json": _schema(
            required=(
                "model",
                "reasons",
                "showBufferingUi",
                "threadId",
                "turnId",
                "useCases",
            ),
            properties=(
                "model",
                "reasons",
                "showBufferingUi",
                "threadId",
                "turnId",
                "useCases",
            ),
        ),
    }
    for name, document in documents.items():
        (schema_root / name).write_text(json.dumps(document), encoding="utf-8")


def build_reviewer_graph(root: Path) -> dict:
    study = root / "study"
    reviewer_root = study / "reviewer-calibration"
    reviewer_root.mkdir(parents=True)
    projection = studies.semantic_projection(
        campaign_id="reviewer-campaign",
        study_id="study-01",
        study_profile="d0-sqw",
        skill_id="software-quality-workflows",
        controller_content_hash=HASH,
        output_schema=studies.reviewer_output_schema(),
    )
    descriptors = host.reviewer_request_descriptors(
        phase="d0",
        projection=projection,
    )
    required = [
        {
            "request_id": descriptor["request_id"],
            "stage": "d0",
            "study": "study-01",
            "family": "reviewer_calibration",
            "request_kind": "context_isolated_review",
            "subject_id": descriptor["subject_id"],
            "arm": None,
            "input_binding_hash": descriptor["input_binding_hash"],
            "output_schema_hash": descriptor["output_schema_hash"],
            "requested_model": host.REVIEWER_MODEL,
            "requested_reasoning_effort": host.REVIEWER_EFFORT,
            "requested_service_tier": host.REVIEWER_SERVICE_TIER,
            "attempt_index": 0,
            "predecessor_request_id": None,
            "activation": "required",
        }
        for descriptor in descriptors
    ]
    attempt = root / "attempt"
    attempt.mkdir()
    manifest = attempt / "request-manifest.json"
    campaign.write_request_manifest(
        manifest,
        campaign_id="reviewer-campaign",
        required_requests=required,
        conditional_requests=[],
    )
    contract = attempt / "phase-contract.json"
    contract.write_text(
        '{"schema_version":"test-phase-contract/1.0"}\n',
        encoding="utf-8",
    )
    campaign.initialize_attempt(
        attempt,
        attempt_id="reviewer-attempt",
        campaign_id="reviewer-campaign",
        plan_sha256=HASH,
        candidate_revision="2" * 40,
        candidate_source_tree_hash=HASH,
        candidate_plugin_tree_hash=HASH,
        controller_content_hash=HASH,
        evaluator_source_hash=HASH,
        phase_contract_path=contract,
        request_manifest_path=manifest,
        stage="d0",
        continuation_token="reviewer-continuation",
    )
    paths = {
        "packet_path": reviewer_root / "packet.json",
        "output_schema_path": reviewer_root / "output-schema.json",
        "sealed_mapping_path": reviewer_root / "sealed-mapping.json",
    }
    for path, value in (
        (paths["packet_path"], projection["packet"]),
        (paths["output_schema_path"], projection["output_schema"]),
        (paths["sealed_mapping_path"], projection["sealed_mapping"]),
    ):
        artifacts.write_json(path, value)
    return {
        "study_root": study,
        "attempt_root": attempt,
        "reviewer_root": reviewer_root,
        "descriptors": descriptors,
        "projection": projection,
        **paths,
    }


def reviewer_response(graph: dict, *, severity: float = 0) -> dict:
    return {
        "schema_version": studies.RATINGS_SCHEMA,
        "ratings": [
            {"label": "pass", "severity": severity}
            for _ in graph["projection"]["packet"]["examples"]
        ],
    }


def prepared_pair(graph: dict) -> list[dict]:
    envelopes = host.reviewer_prepare(**{
        key: graph[key]
        for key in (
            "study_root",
            "attempt_root",
            "reviewer_root",
            "descriptors",
            "packet_path",
            "output_schema_path",
            "sealed_mapping_path",
        )
    })
    for sequence, envelope in enumerate(envelopes, 1):
        host.reviewer_ack(
            reviewer_root=graph["reviewer_root"],
            reviewer_id=envelope["reviewer_id"],
            agent_id=f"agent-{sequence}",
            task_name=envelope["task_name"],
            ack_sequence=sequence,
        )
    return envelopes


def completed_result(graph: dict, envelope: dict, sequence: int) -> dict:
    return host.reviewer_result(
        attempt_root=graph["attempt_root"],
        reviewer_root=graph["reviewer_root"],
        reviewer_id=envelope["reviewer_id"],
        agent_id=f"agent-{sequence - 2}",
        task_name=envelope["task_name"],
        host_terminal_status="completed",
        raw_response=reviewer_response(graph),
        result_consumed_sequence=sequence,
        observable_extra_turns=0,
        observable_followups=0,
        observable_tool_events=[],
    )


def host_manifest() -> dict:
    return {
        "identity": {
            "execution": {
                "provider": "local-synthetic",
                "model": "fixture-model",
                "model_revision": "fixture-revision",
                "prompt_hash": HASH,
                "skill_hash": HASH,
                "catalog_hash": HASH,
                "tool_schema_hash": HASH,
                "policy_hash": HASH,
                "pricing_id": "fixture-pricing",
            },
        },
    }


def host_request(kind: str = "execute_case") -> dict:
    request = {
        "record_type": "skill-evaluator-host-request/1",
        "request_hash": HASH,
        "envelope": {
            "plan_id": "pl-" + "a" * 24,
            "plan_hash": HASH,
            "entry_ordinal": 0,
            "entry_id": "pe-" + "b" * 24,
            "run_id": "run-" + "c" * 24,
            "attempt": 1,
            "request_kind": kind,
        },
        "payload": (
            {"capability": "force_load"}
            if kind != "execute_case"
            else {
                "case": {"case_id": "case-one", "timeout_seconds": 30},
                "turns": [{
                    "turn_id": "turn-1",
                    "checkpoint": "final",
                    "input": {
                        "kind": "user_message",
                        "content": "Complete the local fixture.",
                    },
                    "open_obligations": ["outcome"],
                    "due_obligations": ["outcome"],
                }],
                "treatment": {
                    "causal_role": "candidate",
                    "profile": "candidate/force_loaded",
                },
                "catalog": [{"id": "skill-under-test"}],
                "execution_context": {"context_sources": []},
                "permission_policy": HASH,
            }
        ),
    }
    request["request_hash"] = artifacts.canonical_hash({
        key: value for key, value in request.items() if key != "request_hash"
    })
    return request


def write_contract(
    root: Path,
    request: dict,
    *,
    allowed: list[str] | None = None,
    expected: list[str] | None = None,
    protected: list[str] | None = None,
    transfer: dict | None = None,
) -> Path:
    path = root / "fixtures/case-one/case.contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.write_json(path, {
        "schema_version": "frontier-case-contract/1.0",
        "read_only": False,
        "allowed_change_paths": allowed or [],
        "expected_change_paths": expected or [],
        "protected_paths": protected or [],
        "content_requirements": {},
        "verification_argv": None,
        "transfer_source": transfer,
    })
    request["payload"]["execution_context"]["context_sources"] = [{
        "path": "fixtures/case-one/case.contract.json",
        "sha256": artifacts.file_hash(path),
    }]
    request["request_hash"] = artifacts.canonical_hash({
        key: value for key, value in request.items() if key != "request_hash"
    })
    return path


def completed_turn(
    *,
    status: str = "completed",
    answer: str = "Completed.",
    usage: dict | None = None,
) -> dict:
    timed_out = status == "timeout"
    return {
        "terminal": {"status": status},
        "final_answer": answer,
        "commands": [],
        "usage": (
            {"inputTokens": 10, "outputTokens": 5, "cachedInputTokens": 2}
            if usage is None and not timed_out
            else usage
        ),
        "runtime_ms": 600000 if timed_out else 7,
        "timed_out": timed_out,
        "host_safety_review": {
            "capture_status": "captured",
            "host_safety_review_count": int(timed_out),
            "host_safety_review_latency_ms": 599000 if timed_out else 0,
        },
        "stderr_sha256": HASH,
    }


def bind_fake_turn(
    monkeypatch: Any,
    turn: dict,
    mutate: Any = None,
) -> list[dict]:
    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        if mutate:
            mutate()
        return turn

    monkeypatch.setattr(host, "codex_runtime_from_host", lambda _: {})
    monkeypatch.setattr(host, "run_codex_turn", run)
    return calls


def planner_source(root: Path, case_ids: list[str]) -> str:
    artifact_root = root / "artifacts"
    artifact_root.mkdir()
    entries = [
        {
            "entry_id": f"pe-{case_id}-{role}",
            "case_id": case_id,
            "repeat": 1,
            "treatment_id": role,
            "disposition": "execute",
        }
        for case_id in case_ids
        for role in ("baseline", "candidate")
    ]
    plan = artifacts.self_hashed({"entries": entries}, "plan_hash")
    (root / "execution-plan-v1.json").write_bytes(artifacts.canonical_bytes(plan))
    artifacts.write_json(root / "eval-spec-v5.json", {
        "treatments": [
            {
                "treatment_id": role,
                "causal_role": role,
                "profile": f"{role}/profile",
            }
            for role in ("baseline", "candidate")
        ],
    })
    rows = []
    for entry in entries:
        entry_id = entry["entry_id"]
        artifact_dir = f"entries/{entry_id}/attempt-0001"
        attempt = artifact_root / artifact_dir
        deliverable = (
            attempt / f"workspace/fixtures/{entry['case_id']}/PLAN.md"
        )
        deliverable.parent.mkdir(parents=True)
        deliverable.write_text(
            f"# {entry['case_id']} {entry['treatment_id']}\n",
            encoding="utf-8",
        )
        deliverable_binding = artifacts.artifact_binding(
            deliverable,
            attempt / "workspace",
        )
        deliverable_binding["encoding"] = "utf-8"
        manifest_path = attempt / "fixture-final-manifest.json"
        manifest_path.write_bytes(artifacts.canonical_bytes({
            "schema_version": 1,
            "files": [deliverable_binding],
        }))
        receipt_value = artifacts.self_hashed({
            "run": {
                "valid": True,
                "terminal": "completed",
                **{
                    key: entry[key]
                    for key in (
                        "entry_id",
                        "case_id",
                        "repeat",
                        "treatment_id",
                    )
                },
                "plan_hash": plan["plan_hash"],
            },
            "artifacts": [artifacts.artifact_binding(manifest_path, attempt)],
        }, "receipt_hash")
        receipt_path = attempt / "receipt.json"
        receipt_path.write_bytes(artifacts.canonical_bytes(receipt_value))
        rows.append({
            "entry_id": entry_id,
            "artifact_dir": artifact_dir,
            "receipt": artifacts.artifact_binding(receipt_path, artifact_root),
        })
    (artifact_root / "index.jsonl").write_bytes(
        b"".join(artifacts.canonical_bytes(row) + b"\n" for row in rows),
    )
    return plan["plan_hash"]


def p4_steps(candidate_runtime: int = 100) -> list[dict]:
    steps = []
    for step_id in (
        "B1",
        "B2",
        "B3",
        "B4",
        "F1",
        "F2",
        "F3",
        "R1",
        "R2",
        "R3",
        "S1",
        "S2",
    ):
        arms = {}
        for arm in ("baseline", "candidate", "prior"):
            arms[arm] = {
                "protocol_residue_count": 0,
                "failed_command_residue_count": 0,
                "probe_count": 0,
                "duplicate_test_count": 0,
                "permanent_refactor_test_count": 0,
                "permanent_test_loc": 0,
                "runtime_ns": {
                    "measured": [
                        candidate_runtime if arm == "candidate" else 100
                    ] * 5,
                },
                "seeded_faults": {"detected": 1, "total": 1},
                "task_pass": True,
                "normalized_product_tree_hash": hash_value("1"),
                "protected_tests_pass": True,
                "full_tests_pass": True,
            }
        steps.append({"step_id": step_id, "arms": arms})
    return steps


def p4_identity() -> dict[str, str]:
    return {
        "candidate_revision": "1" * 40,
        **{
            field: hash_value(digit)
            for field, digit in (
                ("candidate_source_tree_hash", "2"),
                ("candidate_plugin_tree_hash", "3"),
                ("controller_content_hash", "4"),
                ("evaluator_source_hash", "5"),
            )
        },
    }


def controller_tree(root: Path) -> Path:
    root.mkdir()
    for relative in source_proof.CONTROLLER_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
    return root


def release_studies(root: Path) -> tuple[dict[str, Path], Path]:
    roots = {}
    for study_id in reports.STUDIES:
        study = root / study_id
        for relative in reports.STUDY_FILES.values():
            path = study / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if relative in {
                reports.STUDY_FILES["summary"],
                reports.STUDY_FILES["failure_index"],
            }:
                path.write_bytes(artifacts.canonical_bytes({}))
            else:
                artifacts.write_json(path, {})
        roots[study_id] = study
    join = root / "join.json"
    artifacts.write_json(join, {})
    return roots, join


def bundle_source_tree(root: Path) -> set[str]:
    skills = {"alpha-skill", "beta-skill"}
    root.mkdir()
    for skill in skills:
        path = root / skill / "SKILL.md"
        path.parent.mkdir()
        path.write_text(f"# {skill}\n", encoding="utf-8")
    manifest = {
        "skills": [
            {"id": skill, "path": skill}
            for skill in sorted(skills)
        ],
    }
    (root / "bundle-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return skills
