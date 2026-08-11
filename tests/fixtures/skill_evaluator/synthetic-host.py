#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import sys
import time


def _emit(value: object) -> None:
    print(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        flush=True,
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _artifact(name: str, value: object) -> dict[str, str]:
    path = Path(name)
    payload = _canonical_bytes(value)
    path.write_bytes(payload)
    return {
        "path": f"workspace/{path.as_posix()}",
        "digest": "sha256:" + sha256(payload).hexdigest(),
        "encoding": "utf-8",
    }


def _grader() -> int:
    mode = next(
        (
            argument.removeprefix("--mode=")
            for argument in sys.argv[1:]
            if argument.startswith("--mode=")
        ),
        "success",
    )
    if mode == "lifecycle-conformance":
        result = json.loads(Path("result.json").read_text(encoding="utf-8"))
        if result["envelope"]["entry_id"] == os.environ.get(
            "SKILL_EVALUATOR_STOP_ENTRY_ID",
        ):
            Path("verifier-stopped").write_text(
                str(os.getpid()), encoding="utf-8",
            )
            os.kill(os.getpid(), signal.SIGSTOP)
    selected = next(
        (
            argument.removeprefix("--checks=").split(",")
            for argument in sys.argv[1:]
            if argument.startswith("--checks=")
        ),
        ["outcome-check", "safety-check"],
    )
    failed = {
        argument.removeprefix("--fail-check=")
        for argument in sys.argv[1:]
        if argument.startswith("--fail-check=")
    }
    passed_count = sum(check_id not in failed for check_id in selected)
    _emit({
        "overall_pass": not bool(failed),
        "score": round(100 * passed_count / len(selected)),
        "checks": [
            {
                "check_id": check_id,
                "pass": check_id not in failed,
                "evidence": [{
                    "artifact": "result.json",
                    "locator": {"start_line": 1, "end_line": 1},
                    "observation": "synthetic host completed the fixture",
                }],
                "notes": "",
                "uncertainty": "",
            }
            for check_id in selected
        ],
        "missing_evidence": [],
        "grader_failure": False,
        "grader_failure_reason": None,
    })
    return 1 if failed else 0


def _actions(
    payload: dict[str, object],
    artifacts: list[dict[str, str]],
    first_seq: int,
    mode: str,
    principal_id: str,
    tool_schema_id: str,
) -> list[dict[str, object]]:
    actions = []
    for offset, tool_id in enumerate(
        payload["execution_context"]["expected_tools"],
    ):
        action_id = f"action.{tool_id}"
        proposed = _artifact(
            f"{action_id}-proposed.json",
            {"tool_id": tool_id, "value": "fixture-input"},
        )
        decision = (
            "deny"
            if mode in {
                "deny", "unauthorized-execution", "deny-hidden-execution",
            }
            else "allow_with_changes"
            if mode in {"allow-with-changes", "approval-mismatch"}
            else "allow"
        )
        executed = (
            _artifact(
                f"{action_id}-executed.json",
                {"tool_id": tool_id, "value": "approved-fixture-input"},
            )
            if decision == "allow_with_changes"
            else proposed
        )
        authorization = _artifact(
            f"{action_id}-authorization.json",
            {
                "decision": decision,
                "approved_input_digest": (
                    None
                    if decision == "deny"
                    else proposed["digest"]
                    if mode == "approval-mismatch"
                    else executed["digest"]
                ),
            },
        )
        backend = _artifact(
            f"{action_id}-backend.json",
            {"status": "ok", "tool_id": tool_id},
        )
        transform = _artifact(
            f"{action_id}-transform.json",
            {"kind": "identity", "source_digest": backend["digest"]},
        )
        effect = _artifact(
            f"{action_id}-effect.json",
            {"confirmed": True, "tool_id": tool_id},
        )
        blocked = decision == "deny" and mode != "unauthorized-execution"
        tool_schema = _artifact(
            f"{action_id}-tool-schema.json",
            {"schema_id": tool_schema_id, "type": "object"},
        )
        artifacts.extend([proposed, authorization, tool_schema])
        if executed is not proposed:
            artifacts.append(executed)
        if not blocked:
            artifacts.extend([backend, transform, effect])
        stage_names = [
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
        stage_artifacts = {
            "invoked": proposed,
            "authorization_requested": proposed,
            "authorization_resolved": authorization,
            "executed": executed,
            "raw_backend_result": backend,
            "model_delivered_result": backend,
            "rendered_or_displayed": transform,
            "effect_observed": effect,
            "effect_confirmed": effect,
        }
        actions.append({
            "action_id": action_id,
            "principal_id": principal_id,
            "tool_identity": {
                "server": "fixture-server",
                "name": tool_id,
                "schema": tool_schema,
                "description": "fixture description",
                "annotations": {},
            },
            "entity": "fixture-entity",
            "target": "fixture-target",
            "scope": "fixture",
            "privilege": "standard",
            "intended_effect": "record fixture effect",
            "proposed_input": proposed,
            "authorization_decisions": [{
                "source_id": "fixture-policy",
                "source_kind": "policy",
                "decision": decision,
                "reason_keys": [f"fixture-{decision}"],
                "policy_matcher": "exact fixture matcher",
                "policy_version": "1",
                "artifact": authorization,
            }],
            "resolution_algorithm": "deny-overrides-then-changes-then-allow",
            "resolved_decision": decision,
            "executed_input": None if blocked else executed,
            "backend_request": None if blocked else executed,
            "backend_result": None if blocked else backend,
            "transport_error": None,
            "model_delivered_result": None if blocked else backend,
            "delivery_transform": None if blocked else transform,
            "visible_result": None if blocked else backend,
            "confirmed_effect": None if blocked else effect,
            "rollback_cleanup_locator": {
                "kind": "text_lines",
                "artifact": authorization["path"] if blocked else effect["path"],
                "start_line": 1,
                "end_line": 1,
            },
            "stages": [
                {
                    "stage": name,
                    "seq": first_seq + offset * len(stage_names) + index,
                    "artifact": stage_artifacts.get(name),
                }
                for index, name in enumerate(
                    stage_names[:8] if blocked else stage_names
                )
            ],
        })
    return actions


def _host(request: dict[str, object], mode: str) -> int:
    if mode == "host-exit":
        return 7
    if mode == "lifecycle-conformance":
        module_path = Path("workspace_module.py")
        module_path.write_text(
            module_path.read_text(encoding="utf-8") + "\nTOUCHED = True\n",
            encoding="utf-8",
        )
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(Path.cwd()))
        import workspace_module

        if workspace_module.VALUE != "package-native":
            return 8
        if not (Path("workspace_tool.sh").stat().st_mode & 0o100):
            return 9
    envelope = request["envelope"]
    if mode == "fail-first-attempt" and envelope["attempt"] == 1:
        return 7
    if mode == "process-timeout":
        time.sleep(2)
    payload = request["payload"]
    now = datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )
    coordination = payload["coordination"]
    slots = (
        coordination["principal_slots"]
        if coordination is not None
        else [{
            "slot_id": slot_id,
            "role": "lead",
            "parent_slot_id": None,
            "allowed_model_class": "fixture-model",
            "context_mode": "single",
            "tool_schema_id": "fixture-tools",
            "authority_id": payload["permission_policy"],
            "budget_ceiling": {
                "turns": len(payload["turns"]),
                "tokens": 1000,
                "seconds": payload["case"]["timeout_seconds"],
                "tool_calls": len(
                    payload["execution_context"]["expected_tools"],
                ),
            },
        } for slot_id in payload["execution_context"]["expected_principal_slots"]]
    )
    lead_id = f"principal-{slots[0]['slot_id']}"
    catalog_ids = [item["id"] for item in payload["catalog"]]
    routing_contract = payload["case"].get("routing_contract")
    target_id = (
        routing_contract["target_skill_id"]
        if routing_contract is not None
        else catalog_ids[0]
    )
    target = [target_id]
    target_catalog_entry = next(
        item for item in payload["catalog"] if item["id"] == target_id
    )
    routing_expectations = {
        item["turn_id"]: item
        for item in (
            routing_contract["expectations"]
            if routing_contract is not None
            else []
        )
        if item["treatment_profile"] == payload["treatment"]["profile"]
    }
    events = []
    checkpoints = []
    artifacts = []
    model_observation = None
    if any(
        item["owner"] == "model" for item in payload["case"]["requirements"]
    ):
        suffix = f"{envelope['entry_id']}-{envelope['attempt']}"
        model_observation = _artifact(
            f"host-observation-{suffix}.json",
            {
                "allowed_change_paths": [],
                "changed_paths": [],
                "protected_paths": [],
                "verification": {"exit_code": 0},
            },
        )
        artifacts.extend([
            model_observation,
            _artifact(
                f"workspace-evidence-{suffix}.json",
                {
                    "initial_files": {},
                    "final_files": {},
                    "changed_paths": [],
                    "diff": "",
                    "verification": {"exit_code": 0},
                },
            ),
            _artifact(f"final-answer-{suffix}.md", "synthetic completion"),
        ])
    stateful = payload["case"]["state_model"]["scope"] != "none"
    for seq, turn in enumerate(payload["turns"]):
        state_artifact = (
            _artifact(
                f"state-{seq:04d}.json",
                {"turn_id": turn["turn_id"], "state": turn["checkpoint"]},
            )
            if stateful
            else None
        )
        if state_artifact is not None:
            artifacts.append(state_artifact)
        checkpoint = {
            "checkpoint_id": f"{turn['checkpoint']}-{seq}",
            "turn_id": turn["turn_id"],
            "seq": seq,
            "state_artifact": state_artifact,
        }
        checkpoints.append(checkpoint)
        expected_routing = routing_expectations.get(turn["turn_id"])
        routing = (
            {
                key: list(expected_routing[key])
                for key in (
                    "declared", "discovered", "loaded", "model_visible",
                    "selected", "invoked", "applied", "order",
                    "composition",
                )
            }
            if expected_routing is not None
            else {
                "declared": target,
                "discovered": target,
                "loaded": target,
                "model_visible": target,
                "selected": target,
                "invoked": target,
                "applied": target,
                "order": target,
                "composition": [],
            }
        )
        if mode == "routing-mismatch" and expected_routing is not None:
            routing["applied"] = (
                []
                if routing["applied"]
                else [routing_contract["target_skill_id"]]
            )
        events.append({
            "record_type": "skill-evaluator-host-event/2",
            "seq": seq,
            "parent_seq": seq - 1 if seq else None,
            "principal_id": lead_id,
            "event_type": "turn_completed",
            "turn_id": turn["turn_id"],
            "checkpoint": checkpoint,
            "payload": {
                "routing": routing,
                "obligations": {
                    "open": list(turn["open_obligations"]),
                    "due": list(turn["due_obligations"]),
                },
            },
            "artifact_locator": None,
            "action": None,
        })
    principals = []
    for slot in slots:
        parent_slot = slot["parent_slot_id"]
        principals.append({
            "principal_id": f"principal-{slot['slot_id']}",
            "slot_id": slot["slot_id"],
            "parent_principal_id": (
                f"principal-{parent_slot}" if parent_slot is not None else None
            ),
            "role": slot["role"],
            "provider": "fixture-provider",
            "model": slot["allowed_model_class"],
            "model_revision": "fixture-revision",
            "session_id": f"{envelope['run_id']}-{slot['slot_id']}",
            "worktree_id": envelope["entry_id"],
            "sandbox_id": f"{envelope['run_id']}-{slot['slot_id']}",
            "context_mode": slot["context_mode"],
            "inherited_context_digest": None,
            "untrusted_input_digest": None,
            "prompt_id": "fixture-prompt",
            "skill_id": target_catalog_entry["id"],
            "catalog_id": payload["treatment"]["base_catalog_id"],
            "tool_schema_id": slot["tool_schema_id"],
            "policy_id": "fixture-policy",
            "authority_id": slot["authority_id"],
            "requested_budget": slot["budget_ceiling"],
            "effective_budget": slot["budget_ceiling"],
            "started_at": now,
            "ended_at": now,
            "status": "completed",
            "span_id": f"span-{slot['slot_id']}",
            "parent_span_id": (
                f"span-{parent_slot}" if parent_slot is not None else None
            ),
        })
    handoffs = []
    if coordination is not None:
        for edge in coordination["dependency_edges"]:
            handoff_id = f"handoff.{edge['from']}.{edge['to']}"
            payload_artifact = _artifact(
                f"{handoff_id}-payload.json",
                {
                    "sender": edge["from"],
                    "receiver": edge["to"],
                    "request_id": envelope["request_id"],
                },
            )
            artifacts.append(payload_artifact)
            receiver = next(
                slot for slot in slots if slot["slot_id"] == edge["to"]
            )
            handoffs.append({
                "handoff_id": handoff_id,
                "span_id": f"handoff-span-{edge['from']}-{edge['to']}",
                "sender_principal_id": f"principal-{edge['from']}",
                "receiver_principal_id": f"principal-{edge['to']}",
                "task": payload["execution_context"]["task"],
                "scope": "declared dependency edge",
                "success_criteria": ["return schema-valid result"],
                "deadline": None,
                "payload": payload_artifact,
                "context_supplied": [payload_artifact],
                "evidence_supplied": [],
                "intentionally_omitted": [],
                "authority_transferred": [],
                "capabilities_transferred": [],
                "expected_output_schema_id": receiver[
                    "expected_return_schema_id"
                ],
                "status": "result",
                "raw_result": payload_artifact,
                "transform": {"kind": "none", "artifact": None},
            })
            receiver_principal = next(
                principal for principal in principals
                if principal["slot_id"] == edge["to"]
            )
            if receiver_principal["context_mode"] == "scoped_handoff":
                receiver_principal["inherited_context_digest"] = payload_artifact[
                    "digest"
                ]
    context_components = []
    controlled_context_bytes = 0
    if routing_contract is not None:
        catalog_artifact = _artifact(
            "catalog-context.json",
            {
                "catalog": payload["catalog"],
                "target_skill_id": routing_contract["target_skill_id"],
            },
        )
        artifacts.append(catalog_artifact)
        controlled_context_bytes = Path(
            catalog_artifact["path"].removeprefix("workspace/"),
        ).stat().st_size
        context_components.append({
            "component_id": "effective-catalog",
            "kind": "metadata",
            "source_path": catalog_artifact["path"],
            "artifact": catalog_artifact,
            "bytes": controlled_context_bytes,
            "tokens": None,
            "occurrence": 1,
        })
    for principal in principals:
        if principal["context_mode"] != "forked":
            continue
        context_artifact = _artifact(
            f"{principal['principal_id']}-inherited-context.json",
            {
                "parent_principal_id": principal["parent_principal_id"],
                "request_id": envelope["request_id"],
            },
        )
        artifacts.append(context_artifact)
        principal["inherited_context_digest"] = context_artifact["digest"]
        component_bytes = Path(
            context_artifact["path"].removeprefix("workspace/"),
        ).stat().st_size
        controlled_context_bytes += component_bytes
        context_components.append({
            "component_id": f"{principal['slot_id']}-inherited-context",
            "kind": "protocol_output",
            "source_path": context_artifact["path"],
            "artifact": context_artifact,
            "bytes": component_bytes,
            "tokens": None,
            "occurrence": 1,
        })
    actions = _actions(
        payload,
        artifacts,
        len(events),
        mode,
        lead_id,
        slots[0]["tool_schema_id"],
    )
    assertions = []
    if model_observation is not None:
        assertions.append({
            "claim": "outcome-complete",
            "artifact": model_observation,
            "locally_verifiable": True,
        })
    for contract in payload["observation_contracts"]:
        relative = contract["artifact"].removeprefix("workspace/")
        observation = _artifact(
            relative,
            {
                "observation_id": contract["observation_id"],
                "value": (
                    "tampered"
                    if mode == "observation-mismatch"
                    else "supported"
                ),
            },
        )
        artifacts.append(observation)
        if contract["observation_id"] == "untrusted-tool-result":
            for principal in principals:
                principal["untrusted_input_digest"] = observation["digest"]
        assertions.append({
            "claim": f"captured {contract['observation_id']}",
            "artifact": observation,
            "locally_verifiable": True,
        })
    for fault in payload["fault_script"]:
        fault_artifact = _artifact(
            f"{fault['fault_id']}.json",
            {
                "fault_id": fault["fault_id"],
                "effect": fault["effect"],
                "resolution": fault["expected_recovery"],
            },
        )
        artifacts.append(fault_artifact)
        if mode == "fault-not-triggered":
            continue
        record = {
            "fault_id": fault["fault_id"],
            "locator": {
                "kind": "text_lines",
                "artifact": fault_artifact["path"],
                "start_line": 1,
                "end_line": 1,
            },
        }
        target_turn = fault["trigger"]["turn_id"]
        target_event = next(
            event for event in events
            if target_turn is None or event["turn_id"] == target_turn
        )
        target_event["payload"].setdefault("faults", {
            "injected": [],
            "observed": [],
            "recovered": [],
        })
        for phase in ("injected", "observed", "recovered"):
            target_event["payload"]["faults"][phase].append(record)
    if mode == "principal-budget-overrun":
        principals[-1]["effective_budget"] = {
            **principals[-1]["effective_budget"],
            "tokens": principals[-1]["requested_budget"]["tokens"] + 1,
        }
    elif mode == "principal-context-mismatch":
        principals[-1]["inherited_context_digest"] = "sha256:" + "0" * 64
    elif mode == "principal-cycle" and len(principals) > 1:
        principals[0]["parent_principal_id"] = principals[-1]["principal_id"]
    elif mode == "principal-span-mismatch" and len(principals) > 1:
        principals[-1]["parent_span_id"] = "span-mismatch"
    elif mode == "principal-authority-mismatch":
        principals[-1]["authority_id"] = "unexpected-authority"
    if mode == "async-delivery" and len(events) > 1:
        events[0]["payload"]["delivery_order"] = 1
        events[1]["payload"]["delivery_order"] = 0
    elif mode == "causal-cycle" and len(events) > 1:
        events[0]["parent_seq"] = 1
        events[1]["parent_seq"] = 0
    if mode == "handoff-transform-missing" and handoffs:
        handoffs[0]["transform"] = {"kind": "summary", "artifact": None}
    elif mode == "handoff-schema-mismatch" and handoffs:
        handoffs[0]["expected_output_schema_id"] = "unexpected-schema"
    elif mode == "handoff-result-missing" and handoffs:
        handoffs[0]["raw_result"] = None
    elif mode == "handoff-premature-result" and handoffs:
        handoffs[0]["status"] = "accepted"
    elif mode == "duplicate-handoff" and handoffs:
        handoffs.append(dict(handoffs[0]))
    elif mode == "partial-join-silent" and handoffs:
        handoffs[0]["status"] = "timeout"
        handoffs[0]["raw_result"] = None
    if mode == "action-principal-mismatch" and actions:
        actions[0]["principal_id"] = "principal-unknown"
    elif mode == "action-tool-mismatch" and actions:
        actions[0]["tool_identity"]["name"] = "unexpected-tool"
    elif mode == "action-stage-artifact-mismatch" and actions:
        next(
            stage for stage in actions[0]["stages"]
            if stage["stage"] == "raw_backend_result"
        )["artifact"] = actions[0]["proposed_input"]
    elif mode == "authorization-resolution-mismatch" and actions:
        actions[0]["authorization_decisions"][0]["decision"] = "deny"
    elif mode == "deny-hidden-execution" and actions:
        proposed = actions[0]["proposed_input"]
        for field in (
            "executed_input",
            "backend_request",
            "backend_result",
            "model_delivered_result",
            "delivery_transform",
            "visible_result",
            "confirmed_effect",
        ):
            actions[0][field] = proposed
    elif mode == "duplicate-action" and actions:
        actions.append(dict(actions[0]))
    if mode == "state-obligation-mismatch" and events:
        events[-1]["payload"]["obligations"]["due"] = []
    state_model = payload["case"]["state_model"]
    cleanup_state = (
        state_model["expected_cleanup_state"]
        if state_model["scope"] != "none"
        else "not_applicable"
    )
    if mode == "state-cleanup-mismatch":
        cleanup_state = "unexpected"
    result = {
        "record_type": "skill-evaluator-host-result/2",
        "terminal": True,
        "terminal_status": "completed",
        "envelope": envelope,
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "principals": principals,
        "handoffs": handoffs,
        "actions": actions,
        "artifacts": artifacts,
        "state": checkpoints,
        "cleanup": {"status": "clean", "state": cleanup_state},
        "usage": {
            "pricing_identity": "fixture-pricing",
            "host_safety_review": {
                "capture_status": "captured",
                "host_safety_review_count": 1,
                "host_safety_review_latency_ms": 9,
            },
            "records": [
                {
                    "principal_id": principal["principal_id"],
                    "turn_id": payload["turns"][0]["turn_id"],
                    "phase": "execute",
                    "call_id": f"call-{principal['slot_id']}",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_tokens": 5 if mode == "cache-hit" else 0,
                    "cache_write_tokens": 0,
                    "queue_ms": 0,
                    "runtime_ms": 1,
                    "tool_calls": 0,
                    "retries": 0,
                    "rework": 0,
                    "network_calls": 0,
                    "residue_count": 0,
                    "requested_effort": 1,
                    "effective_effort": 1,
                }
                for principal in principals
            ],
        },
        "context": {
            "status": "captured",
            "bytes": sum(item["bytes"] for item in context_components),
            "tokens": 0,
            "controlled_bytes": controlled_context_bytes,
            "unique_reference_bytes": 0,
            "controlled_core_bytes": controlled_context_bytes,
            "components": context_components,
        },
        "assertions": assertions,
    }
    if mode == "sequence-gap":
        events[0]["seq"] = 1
    elif mode == "identity-mismatch":
        result["envelope"] = {
            **result["envelope"],
            "request_id": "request.mismatch",
        }
    elif mode == "treatment-failure":
        result["terminal_status"] = "failed"
        result["treatment_error"] = "synthetic treatment failure"
    elif mode == "treatment-timeout":
        result["terminal_status"] = "timeout"
        result["timeout"] = True
        result["treatment_error"] = "synthetic treatment timeout"
    elif mode == "host-model-timeout":
        result["terminal_status"] = "timeout"
        result["timeout"] = True
        result["treatment_error"] = "synthetic model-task timeout"
        result["provider_error_code"] = None
        result["failure_class"] = "model_task_timeout"
    elif (
        mode == "transient-first-attempt"
        and envelope["attempt"] == 1
    ):
        result["terminal_status"] = "failed"
        result["treatment_error"] = "synthetic response stream disconnected"
        result["provider_error_code"] = "responseStreamDisconnected"
        result["failure_class"] = "official_transient"
    elif mode == "protocol-gap-first-attempt" and envelope["attempt"] == 1:
        result["terminal_status"] = "protocol_error"
        result["protocol_error"] = {
            "kind": "malformed_record",
            "message": (
                "Codex stream has incomplete items: stdout record 8 "
                "(item.started/command_execution)"
            ),
            "seq": None,
            "artifact": None,
        }
    elif mode == "treatment-cancel":
        result["terminal_status"] = "cancelled"
        result["treatment_error"] = "synthetic treatment cancellation"
    for event in events:
        _emit(event)
    _emit(result)
    if mode == "duplicate-terminal":
        _emit(result)
    return 0


def _model_grade(request: dict[str, object]) -> int:
    envelope = request["envelope"]
    payload = request["payload"]
    blinded = payload["blinded_input"]
    grade = _artifact(
        f"model-grade-{payload['grader_id']}.json",
        {
            "batch_id": blinded["batch_id"],
            "items": [{
                "item_id": item["item_id"],
                "checks": [{
                    "id": check["id"],
                    "pass": True,
                    "notes": "synthetic model grade",
                    "uncertainty": "none",
                } for check in item["checks"]],
            } for item in blinded["items"]],
        },
    )
    result = {
        "record_type": "skill-evaluator-host-result/2",
        "terminal": True,
        "terminal_status": "completed",
        "envelope": envelope,
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "principals": [],
        "handoffs": [],
        "actions": [],
        "artifacts": [grade],
        "state": [],
        "cleanup": {"status": "clean"},
        "usage": {
            "pricing_identity": "fixture-pricing",
            "host_safety_review": {
                "capture_status": "missing",
                "host_safety_review_count": 0,
                "host_safety_review_latency_ms": 0,
            },
            "records": [{
                "principal_id": f"grader-{payload['grader_id']}",
                "turn_id": None,
                "phase": "model_grade",
                "call_id": f"grade-{payload['grader_id']}",
                "input_tokens": 8,
                "output_tokens": 4,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "queue_ms": 0,
                "runtime_ms": 1,
                "tool_calls": 0,
                "retries": 0,
                "rework": 0,
                "network_calls": 0,
                "residue_count": 0,
                "requested_effort": 1,
                "effective_effort": 1,
            }],
        },
        "context": {
            "status": "captured",
            "bytes": 0,
            "tokens": 0,
            "controlled_bytes": 0,
            "unique_reference_bytes": 0,
            "controlled_core_bytes": 0,
            "components": [],
        },
        "assertions": [{
            "claim": "blinded model grade completed",
            "artifact": grade,
            "locally_verifiable": True,
        }],
    }
    _emit(result)
    return 0


def _probe(request: dict[str, object]) -> int:
    probe = _artifact(
        "reset-probe.json",
        {
            "strategy": request["payload"]["strategy"],
            "status": "pass",
        },
    )
    _emit({
        "record_type": "skill-evaluator-host-result/2",
        "terminal": True,
        "terminal_status": "completed",
        "envelope": request["envelope"],
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "principals": [],
        "handoffs": [],
        "actions": [],
        "artifacts": [probe],
        "state": [],
        "cleanup": {"status": "clean"},
        "usage": {"pricing_identity": "fixture-pricing", "records": []},
        "context": {
            "status": "captured",
            "bytes": 0,
            "tokens": 0,
            "controlled_bytes": 0,
            "unique_reference_bytes": 0,
            "controlled_core_bytes": 0,
            "components": [],
        },
        "assertions": [{
            "claim": "reset probe passed",
            "artifact": probe,
            "locally_verifiable": True,
        }],
    })
    return 0


def main() -> int:
    mode = next(
        (
            argument.removeprefix("--mode=")
            for argument in sys.argv[1:]
            if argument.startswith("--mode=")
        ),
        "success",
    )
    line = sys.stdin.readline()
    if not line:
        return _grader()
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        return 2
    if request.get("envelope", {}).get("request_kind") == "model_grade":
        return _model_grade(request)
    if request.get("envelope", {}).get("request_kind") == "probe_capability":
        return _probe(request)
    return _host(request, mode)


raise SystemExit(main())
