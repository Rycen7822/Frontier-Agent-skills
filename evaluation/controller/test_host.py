from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import threading
from unittest import mock

import pytest

from . import artifacts, campaign, host, source_proof, studies, workspace
from .controller_testkit import (
    HASH,
    app_server_schema_tree,
    bind_fake_turn,
    build_reviewer_graph,
    completed_turn,
    completed_result,
    host_manifest,
    host_request,
    prepared_pair,
    reviewer_response,
    write_contract,
)


@pytest.fixture
def reviewer_graph(tmp_path: Path) -> dict:
    return build_reviewer_graph(tmp_path)


def test_transient_classification_uses_only_structured_host_codes() -> None:
    assert host.structured_host_failure_class({
        "status": "failed",
        "error": {"codexErrorInfo": "serverOverloaded"},
    }) == "official_transient"
    assert host.structured_host_failure_class({
        "status": "failed",
        "error": {
            "codexErrorInfo": {
                "responseStreamDisconnected": {"httpStatusCode": 503},
            },
        },
    }) == "official_transient"
    assert host.structured_host_failure_class({
        "status": "failed",
        "error": {"codexErrorInfo": "usageLimitExceeded"},
    }) == "provider_nonretryable"
    assert host.structured_host_error_code({
        "status": "failed",
        "error": {"codexErrorInfo": "usageLimitExceeded"},
    }) == "usageLimitExceeded"
    assert host.structured_host_failure_class({
        "status": "failed",
        "error": {"message": "server overloaded; please retry"},
    }) is None
    assert host.host_safety_review_observation(
        [
            {
                "method": "model/safetyBuffering/updated",
                "params": {
                    "threadId": "thread-a",
                    "turnId": "turn-a",
                    "showBufferingUi": True,
                },
            },
            {
                "method": "model/safetyBuffering/updated",
                "params": {
                    "threadId": "thread-a",
                    "turnId": "turn-a",
                    "showBufferingUi": False,
                },
            },
            {
                "method": "model/safetyBuffering/updated",
                "params": {
                    "threadId": "thread-a",
                    "turnId": "turn-a",
                    "showBufferingUi": True,
                },
            },
        ],
        [1.0, 2.0, 3.0],
        thread_id="thread-a",
        turn_id="turn-a",
        end_time=4.0,
    ) == {
        "capture_status": "captured",
        "host_safety_review_count": 2,
        "host_safety_review_latency_ms": 2000.0,
    }


@pytest.mark.parametrize(
    "kind",
    ["execute_case", "model_grade", "probe_capability", "cleanup"],
)
def test_four_host_request_kinds_have_one_terminal_result(kind: str, tmp_path: Path) -> None:
    records = host.pure_fake_records(host_request(kind), host_manifest(), tmp_path)
    terminal = [
        item
        for item in records
        if item["record_type"] == "skill-evaluator-host-result/1"
    ]
    assert len(terminal) == 1
    assert terminal[0]["terminal"] is True
    assert terminal[0]["context"]["status"] == "captured"
    assert terminal[0]["cleanup"]["status"] == "clean"
    assert all(artifacts.file_hash(tmp_path / Path(item["path"]).name) == item["sha256"] for item in terminal[0]["artifacts"])


def test_identity_envelope_rejects_nul_without_shell_transport() -> None:
    request = host_request()
    request["payload"]["case"]["case_id"] = "bad\x00case"
    request["request_hash"] = artifacts.canonical_hash({
        key: value for key, value in request.items() if key != "request_hash"
    })
    with pytest.raises(host.HostError):
        host.pure_fake_records(request, host_manifest())


def test_request_hash_and_unknown_kind_fail_closed() -> None:
    changed = host_request()
    changed["payload"]["catalog"] = []
    with pytest.raises(host.HostError):
        host.validate_request(changed)
    unknown = host_request()
    unknown["envelope"]["request_kind"] = "retry"
    unknown["request_hash"] = artifacts.canonical_hash({
        key: value for key, value in unknown.items() if key != "request_hash"
    })
    with pytest.raises(host.HostError):
        host.validate_request(unknown)


def test_fake_execution_has_single_principal_and_closed_context(
    tmp_path: Path,
) -> None:
    request = host_request()
    records = host.pure_fake_records(request, host_manifest())
    result = records[-1]
    assert [(p["slot_id"], "." in p["started_at"]) for p in result["principals"]] == [("main", False)]
    assert [event["checkpoint"] for event in records[:-1]] == result["state"]
    assert (
        result["context"]["controlled_core_bytes"]
        == result["context"]["controlled_bytes"]
        - result["context"]["unique_reference_bytes"]
    )
    candidate = tmp_path / "candidate/SKILL.md"
    prior = tmp_path / "prior/SKILL.md"
    candidate.parent.mkdir()
    prior.parent.mkdir()
    candidate.write_text("# candidate\n", encoding="utf-8")
    prior.write_text("# prior\n", encoding="utf-8")
    payload = request["payload"]
    for profile, expected in {
        "baseline/skill_disabled": (None, None),
        "comparator/raw_instructions": (None, None),
        "candidate/force_loaded": (candidate, None),
        "prior/force_loaded": (prior, None),
        "candidate/natural_routing": (None, candidate),
        "comparator/alternative_intervention": (None, candidate),
    }.items():
        payload["treatment"]["profile"] = profile
        assert workspace.selected_skills(payload, candidate, prior) == expected
    payload["catalog"] = [{"id": "software-quality-workflows"}]
    payload["treatment"]["profile"] = "candidate/natural_routing"
    routing = host.routing_for(payload)
    assert {key: routing[key] for key in ("discovered", "loaded", "applied")} == {
        "discovered": ["software-quality-workflows"],
        "loaded": [],
        "applied": [],
    }
    result_file = tmp_path / "result.txt"
    result_file.write_text("wrong\n", encoding="utf-8")
    requirements = {
        "result.txt": {"required": ["expected"], "forbidden": ["wrong"]},
    }
    assert not workspace.content_contract_passes(tmp_path, requirements)
    result_file.write_text("expected\n", encoding="utf-8")
    assert workspace.content_contract_passes(tmp_path, requirements)


def test_host_grader_exact_transport() -> None:
    artifact = {
        "path": "workspace/result-evidence.json",
        "sha256": HASH,
        "encoding": "utf-8",
    }
    result = {
        "terminal_status": "completed",
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "assertions": [
            {"claim": claim, "artifact": artifact, "locally_verifiable": True}
            for claim in ("outcome-complete", "safety-preserved")
        ],
    }
    output = host.deterministic_grade(
        result,
        ["outcome-check", "safety-check"],
    )
    assert {item["check_id"] for item in output["checks"]} == {
        "outcome-check",
        "safety-check",
    }
    assert output["overall_pass"]
    assert set(output["checks"][0]["evidence"][0]) == {
        "artifact",
        "locator",
        "observation",
    }
    with pytest.raises(ValueError):
        host.selected_checks(["arbitrary.json", "--checks=outcome-check"])


def test_reviewer_descriptors_bind_two_context_clean_positional_prompts() -> None:
    projection = studies.semantic_projection(
        campaign_id="campaign-01",
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
    assert len(descriptors) == 2
    assert len({item["reviewer_id"] for item in descriptors}) == 2
    for descriptor in descriptors:
        prompt = descriptor["prompt"]
        assert prompt["schema_version"] == "context-clean-subagent-reviewer-prompt/3.0"
        assert "Do not return reviewer or opaque example identifiers" in prompt["instruction"]
        assert prompt["output_schema"] == projection["output_schema"]


def test_native_attempt_receipt_hash_and_failure_class_are_closed() -> None:
    entry = {
        "request_id": "request-1",
        "input_binding_hash": HASH,
        "output_schema_hash": None,
    }
    receipt = campaign.native_attempt_receipt(entry, terminal_status="completed")
    assert campaign.validate_native_attempt_receipt(receipt) == receipt
    with pytest.raises(artifacts.StateError):
        campaign.native_attempt_receipt(
            entry,
            terminal_status="completed",
            failure_class="official_transient",
        )


def test_capability_attestation_is_in_memory_exact_and_deterministic() -> None:
    evaluator = Path(__file__).resolve().parents[2] / "skill-evaluator"
    arguments = {
        "host_manifest_path": evaluator / "templates/host-manifest.example.json",
        "skill_evaluator_root": evaluator,
    }
    first = source_proof.build_capability_attestation(**arguments)
    assert source_proof.build_capability_attestation(**arguments) == first
    assert set(first) == {
        "schema_version",
        "host_manifest_content_hash",
        "host_adapter_content_hash",
        "host_capability_results",
        "private_transport_results",
        "attestation_hash",
    }
    assert set(first["private_transport_results"]) == set(source_proof.PRIVATE_PROBES)
    for item in (
        *first["host_capability_results"].values(),
        *first["private_transport_results"].values(),
    ):
        assert set(item) == {
            "capability",
            "probe_request_hash",
            "probe_result_hash",
            "status",
        }
        assert item["status"] == "pass"


def test_app_server_preflight_validates_used_union_without_provider(
    tmp_path: Path,
) -> None:
    app_server_schema_tree(tmp_path)
    first = source_proof.validate_app_server_schema_tree(tmp_path)
    assert source_proof.validate_app_server_schema_tree(tmp_path) == first
    assert first["provider_request_count"] == 0
    assert (
        first["root_subagent_spawn_requirement"]
        == source_proof.ROOT_SUBAGENT_SPAWN_REQUIREMENT
    )
    assert first["validated_schema_files"] == sorted(
        source_proof.APP_SERVER_SCHEMA_REQUIREMENTS,
    )
    executable = Path(sys.executable).resolve()
    runtime = {"executable": {"path": str(executable), "sha256": artifacts.file_hash(executable)}}
    with mock.patch.object(host.subprocess, "Popen") as popen:
        host.AppServer(tmp_path, runtime)
    assert popen.call_args.args[0] == [str(executable), *host.APP_SERVER_ARGS]
    assert "PATH" not in popen.call_args.kwargs["env"]
    waiting = object.__new__(host.AppServer)
    waiting.messages = []
    waiting.condition = threading.Condition()
    waiting.process = mock.Mock()
    waiting.process.poll.return_value = None
    assert waiting.wait_for("turn/completed", 0, timeout=0) is None
    waiting.process.stdout = [json.dumps({"id": 7, "method": "item/commandExecution/requestApproval"}), json.dumps({"id": 1, "result": {}})]
    waiting.message_times, waiting.responses, waiting._send = [], {}, mock.Mock()
    waiting._read_stdout()
    waiting._send.assert_called_once_with({"jsonrpc": "2.0", "id": 7, "result": {"decision": "accept"}})
    assert 7 not in waiting.responses and 1 in waiting.responses
    assert host.server_request_result("item/commandExecution/requestApproval", {"additionalPermissions": {"network": {}}}) == {"decision": "decline"}
    assert host.server_request_result("item/permissions/requestApproval", {}) == {"permissions": {}}

    fake_server = mock.Mock()
    fake_server.messages = []
    fake_server.message_times = []
    fake_server.stderr = []
    fake_server.condition = threading.Condition()
    fake_server.request.side_effect = lambda method, _params: (
        {"thread": {"id": "thread-a"}}
        if method == "thread/start"
        else {"turn": {"id": "turn-a"}}
        if method == "turn/start"
        else {}
    )

    def timed_out_wait(_method, _start, *, timeout):
        assert timeout == 600
        fake_server.messages.append({
            "method": "model/safetyBuffering/updated",
            "params": {
                "threadId": "thread-a",
                "turnId": "turn-a",
                "showBufferingUi": True,
            },
        })
        fake_server.message_times.append(host.time.monotonic())
        return None

    fake_server.wait_for.side_effect = timed_out_wait
    with mock.patch.object(host, "AppServer", return_value=fake_server):
        timed_out = host.run_codex_turn(
            workspace=tmp_path,
            prompt="local fixture task",
            explicit_skill=None,
            registered_skill=None,
            timeout_seconds=600,
            codex_runtime=runtime,
        )
    assert timed_out["timed_out"]
    assert timed_out["usage"] is None
    assert timed_out["host_safety_review"]["host_safety_review_count"] == 1
    fake_server.close.assert_called_once_with()
    for call in fake_server.request.call_args_list:
        if call.args[0] in {"thread/start", "turn/start"}:
            assert call.args[1]["approvalPolicy"] == "on-request"

    cached = tmp_path / "cached-codex"
    cached.write_bytes(b"#!/bin/sh\nexit 0\n")
    cached.chmod(0o755)
    cached_runtime = {"executable": {"path": str(cached), "sha256": artifacts.file_hash(cached)}}
    host.validate_codex_runtime(cached_runtime)
    cached.write_bytes(b"#!/bin/sh\nexit 1\n")
    with pytest.raises(host.HostError, match="identity differs"):
        host.validate_codex_runtime(cached_runtime)

    with mock.patch.dict(os.environ, {"PATH": ""}):
        verification = workspace.run_verification(
            tmp_path,
            {
                "verification_argv": [
                    "python3",
                    "-c",
                    "print('bound-python')",
                ],
            },
            5,
        )
    assert verification["exit_code"] == 0
    assert verification["stdout"] == "bound-python\n"
    item_path = tmp_path / "v2/ItemCompletedNotification.json"
    item = json.loads(item_path.read_text(encoding="utf-8"))
    item["definitions"]["ThreadItem"]["oneOf"].pop()
    item_path.write_text(json.dumps(item), encoding="utf-8")
    with pytest.raises(source_proof.ProofError):
        source_proof.validate_app_server_schema_tree(tmp_path)


def test_pair_is_reserved_before_spawn_and_obeys_two_ack_barrier(
    reviewer_graph: dict,
) -> None:
    arguments = {
        key: reviewer_graph[key]
        for key in (
            "study_root",
            "attempt_root",
            "reviewer_root",
            "descriptors",
            "packet_path",
            "output_schema_path",
            "sealed_mapping_path",
        )
    }
    envelopes = host.reviewer_prepare(**arguments)
    assert len(campaign.verify_ledger(
        reviewer_graph["attempt_root"] / "provider-ledger.jsonl",
    )) == 2
    for envelope in envelopes:
        assert re.fullmatch(r"review_[0-9a-f]{32}", envelope["task_name"])
        assert envelope["message"].endswith("\n")
        prompt_path = (
            reviewer_graph["reviewer_root"]
            / envelope["reviewer_id"]
            / "prompt.json"
        )
        assert envelope["message"].encode("utf-8") == prompt_path.read_bytes()
        assert envelope["message_hash"] == artifacts.file_hash(prompt_path)
        assert json.loads(envelope["message"])["schema_version"].endswith("/3.0")
    first, second = envelopes
    host.reviewer_ack(
        reviewer_root=reviewer_graph["reviewer_root"],
        reviewer_id=first["reviewer_id"],
        agent_id="agent-1",
        task_name=first["task_name"],
        ack_sequence=1,
    )
    with pytest.raises(host.HostError):
        completed_result(reviewer_graph, first, 3)
    host.reviewer_ack(
        reviewer_root=reviewer_graph["reviewer_root"],
        reviewer_id=second["reviewer_id"],
        agent_id="agent-2",
        task_name=second["task_name"],
        ack_sequence=2,
    )
    results = [
        completed_result(reviewer_graph, envelope, sequence)
        for envelope, sequence in zip(envelopes, (3, 4), strict=True)
    ]
    assert all(result["terminal_status"] == "completed" for result in results)
    expected = studies.positional_ratings(
        reviewer_response(reviewer_graph),
        reviewer_graph["projection"]["packet"]["examples"],
    )
    assert all(
        result["reviewer_receipt"]["parsed_ratings_hash"]
        == artifacts.canonical_hash(expected)
        for result in results
    )
    pair = host.reviewer_seal(
        study_root=reviewer_graph["study_root"],
        attempt_root=reviewer_graph["attempt_root"],
        reviewer_root=reviewer_graph["reviewer_root"],
        receipt_schema_path=studies.REVIEWER_SCHEMA,
        previously_sealed_roots=[],
    )
    assert pair["both_spawns_acknowledged_before_first_result_consumed"]
    assert len(pair["reviewer_receipts"]) == 2


def test_nonfinite_result_is_terminal(reviewer_graph: dict) -> None:
    first, _ = prepared_pair(reviewer_graph)
    result = host.reviewer_result(
        attempt_root=reviewer_graph["attempt_root"],
        reviewer_root=reviewer_graph["reviewer_root"],
        reviewer_id=first["reviewer_id"],
        agent_id="agent-1",
        task_name=first["task_name"],
        host_terminal_status="completed",
        raw_response=reviewer_response(reviewer_graph, severity=float("nan")),
        result_consumed_sequence=3,
        observable_extra_turns=0,
        observable_followups=0,
        observable_tool_events=[],
    )
    assert result["terminal_status"] == "failed"
    assert result["failure_reason"] == "reviewer severity is not finite"


def test_invalid_result_is_terminal_and_cannot_be_replaced(
    reviewer_graph: dict,
) -> None:
    first, _ = prepared_pair(reviewer_graph)
    invalid = reviewer_response(reviewer_graph)
    invalid["ratings"].pop()
    arguments = {
        "attempt_root": reviewer_graph["attempt_root"],
        "reviewer_root": reviewer_graph["reviewer_root"],
        "reviewer_id": first["reviewer_id"],
        "agent_id": "agent-1",
        "task_name": first["task_name"],
        "host_terminal_status": "completed",
        "result_consumed_sequence": 3,
        "observable_extra_turns": 0,
        "observable_followups": 0,
        "observable_tool_events": [],
    }
    result = host.reviewer_result(raw_response=invalid, **arguments)
    assert result["terminal_status"] == "failed"
    assert result["native_receipt"]["terminal_status"] == "failed"
    with pytest.raises(host.HostError):
        host.reviewer_result(
            raw_response=reviewer_response(reviewer_graph),
            **arguments,
        )
    with pytest.raises(host.HostError):
        host.reviewer_seal(
            study_root=reviewer_graph["study_root"],
            attempt_root=reviewer_graph["attempt_root"],
            reviewer_root=reviewer_graph["reviewer_root"],
            receipt_schema_path=studies.REVIEWER_SCHEMA,
            previously_sealed_roots=[],
        )


def test_rebound_packet_fails_before_any_reservation(reviewer_graph: dict) -> None:
    packet = artifacts.load_json(reviewer_graph["packet_path"])
    payload = packet["examples"][0]["payload"]
    payload["view"]["final_answer"] += " rebound"
    packet["examples"][0]["payload_hash"] = artifacts.canonical_hash(payload)
    packet["packet_hash"] = artifacts.canonical_hash({
        key: value for key, value in packet.items() if key != "packet_hash"
    })
    artifacts.write_json(reviewer_graph["packet_path"], packet)
    with pytest.raises(host.HostError):
        host.reviewer_prepare(**{
            key: reviewer_graph[key]
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
    assert campaign.verify_ledger(
        reviewer_graph["attempt_root"] / "provider-ledger.jsonl",
    ) == []


def test_hardlink_reviewer_graph_is_rejected(reviewer_graph: dict) -> None:
    envelopes = prepared_pair(reviewer_graph)
    for envelope, sequence in zip(envelopes, (3, 4), strict=True):
        completed_result(reviewer_graph, envelope, sequence)
    alias = reviewer_graph["reviewer_root"] / "packet-alias.json"
    os.link(reviewer_graph["packet_path"], alias)
    with pytest.raises(host.HostError):
        host.reviewer_seal(
            study_root=reviewer_graph["study_root"],
            attempt_root=reviewer_graph["attempt_root"],
            reviewer_root=reviewer_graph["reviewer_root"],
            receipt_schema_path=studies.REVIEWER_SCHEMA,
            previously_sealed_roots=[],
        )


def test_codex_execution_projects_bound_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skill = tmp_path / "skill/SKILL.md"
    skill.parent.mkdir()
    skill.write_text("# Fixture\n", encoding="utf-8")
    request = host_request()
    write_contract(tmp_path, request)
    calls = bind_fake_turn(monkeypatch, completed_turn())
    events, result = workspace.execute_codex(
        tmp_path,
        request,
        host_manifest(),
        candidate=skill,
        prior=None,
    )
    assert len(events) == 1
    assert calls[0]["timeout_seconds"] == host.MODEL_TASK_TIMEOUT_SECONDS == 600
    assert result["terminal_status"] == "completed"
    assert result["principals"][0]["effective_budget"]["tokens"] == 15
    assert [item["kind"] for item in result["context"]["components"]] == ["body"]
    assert {item["claim"] for item in result["assertions"]} >= {
        "outcome-complete",
        "transfer-preflight",
    }


def test_timeout_preserves_zero_usage_and_safety_observation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skill = tmp_path / "skill/SKILL.md"
    skill.parent.mkdir()
    skill.write_text("# Fixture\n", encoding="utf-8")
    request = host_request()
    write_contract(tmp_path, request)
    bind_fake_turn(
        monkeypatch,
        completed_turn(status="timeout", answer="", usage=None),
    )
    _, result = workspace.execute_codex(
        tmp_path,
        request,
        host_manifest(),
        candidate=skill,
        prior=None,
    )
    assert result["terminal_status"] == "timeout"
    assert result["failure_class"] == "model_task_timeout"
    assert result["usage"]["records"] == []
    assert result["usage"]["host_safety_review"][
        "host_safety_review_count"
    ] == 1


def test_transfer_substitution_stops_before_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skill = tmp_path / "skill/SKILL.md"
    skill.parent.mkdir()
    skill.write_text("# Fixture\n", encoding="utf-8")
    content = "# Bound handoff\n"
    transfer = {
        "schema_version": "frontier-transfer-source/1.0",
        "bindings": {
            "candidate": {
                "source_case_id": "wp-source",
                "planner_repeat": 1,
                "planner_treatment_id": "candidate",
                "planner_entry_id": "pe-planner",
                "planner_receipt_hash": HASH,
                "planner_plan_hash": HASH,
                "deliverable_path": "fixtures/case-one/PLAN.md",
                "deliverable_sha256": artifacts.raw_hash(content.encode()),
                "deliverable_content": content,
            },
        },
        "profiles": {"candidate/force_loaded": "candidate"},
        "workspace_files": {},
    }
    request = host_request()
    write_contract(
        tmp_path,
        request,
        protected=["fixtures/case-one/PLAN.md"],
        transfer=transfer,
    )
    calls = bind_fake_turn(monkeypatch, completed_turn())
    workspace.execute_codex(
        tmp_path,
        request,
        host_manifest(),
        candidate=skill,
        prior=None,
    )
    assert len(calls) == 1
    (tmp_path / "fixtures/case-one/PLAN.md").write_text(
        "# Substituted\n",
        encoding="utf-8",
    )
    with pytest.raises(workspace.WorkspaceError, match="planner binding"):
        workspace.execute_codex(
            tmp_path,
            request,
            host_manifest(),
            candidate=skill,
            prior=None,
        )
    assert len(calls) == 1


@pytest.mark.parametrize("status", ["completed", "timeout"])
def test_model_grade_is_blinded_and_bound(
    tmp_path: Path,
    monkeypatch,
    status: str,
) -> None:
    prompt = tmp_path / "prompt.md"
    schema = tmp_path / "schema.json"
    prompt.write_text("Grade the bound checks.", encoding="utf-8")
    schema.write_text('{"type":"object"}', encoding="utf-8")
    request = host_request("model_grade")
    request["payload"] = {
        "grader_id": "rubric",
        "batch_hash": HASH,
        "schedule_hash": HASH,
        "blinded_input": {"case_id": "case-one"},
    }
    request["request_hash"] = artifacts.canonical_hash({
        key: value for key, value in request.items() if key != "request_hash"
    })
    turn = completed_turn(
        status=status,
        answer=json.dumps({"overall_pass": True}) if status == "completed" else "",
        usage=None,
    )
    calls = bind_fake_turn(monkeypatch, turn)
    result = workspace.execute_model_grade(
        tmp_path,
        request,
        host_manifest(),
        prompt_path=prompt,
        schema_path=schema,
    )
    assert calls[0]["timeout_seconds"] == host.MODEL_TASK_TIMEOUT_SECONDS
    assert "candidate" not in calls[0]["prompt"]
    if status == "completed":
        assert len(result["artifacts"]) == 1
        assert result["usage"]["records"][0]["phase"] == "model_grade"
    else:
        assert result["terminal_status"] == "timeout"
        assert result["failure_class"] == "model_task_timeout"
        assert result["usage"]["records"] == []
