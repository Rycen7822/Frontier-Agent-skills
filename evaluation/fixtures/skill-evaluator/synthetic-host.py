#!/usr/bin/env python3
"""Minimal successful host used by the public Skill Evaluator lifecycle test."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys


def emit(value: object) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)


def artifact(name: str, value: object) -> dict[str, str]:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    Path(name).write_bytes(payload)
    return {
        "path": f"workspace/{name}",
        "digest": "sha256:" + sha256(payload).hexdigest(),
        "encoding": "utf-8",
    }


def context() -> dict[str, object]:
    return {
        "status": "captured",
        "bytes": 0,
        "tokens": 0,
        "controlled_bytes": 0,
        "unique_reference_bytes": 0,
        "controlled_core_bytes": 0,
        "components": [],
    }


def probe(request: dict[str, object]) -> None:
    reset = artifact(
        "reset-probe.json",
        {
            "strategy": request["payload"]["strategy"],
            "status": "pass",
        },
    )
    emit({
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
        "artifacts": [reset],
        "state": [],
        "cleanup": {"status": "clean"},
        "usage": {"pricing_identity": "fixture-pricing", "records": []},
        "context": context(),
        "assertions": [{
            "claim": "reset probe passed",
            "artifact": reset,
            "locally_verifiable": True,
        }],
    })


def execute(request: dict[str, object]) -> None:
    envelope = request["envelope"]
    payload = request["payload"]
    turn = payload["turns"][0]
    skill_id = payload["catalog"][0]["id"]
    principal_id = "principal-main"
    checkpoint = {
        "checkpoint_id": "final-0",
        "seq": 0,
        "state_artifact": None,
        "turn_id": turn["turn_id"],
    }
    event = {
        "record_type": "skill-evaluator-host-event/2",
        "seq": 0,
        "parent_seq": None,
        "principal_id": principal_id,
        "event_type": "turn_completed",
        "turn_id": turn["turn_id"],
        "checkpoint": checkpoint,
        "payload": {
            "obligations": {
                "open": turn["open_obligations"],
                "due": turn["due_obligations"],
            },
            "routing": {
                key: [] if key == "composition" else [skill_id]
                for key in (
                    "declared", "discovered", "selected", "loaded", "invoked",
                    "applied", "model_visible", "order", "composition",
                )
            },
        },
        "artifact_locator": None,
        "action": None,
    }
    budget = {
        "turns": 1,
        "tokens": 1000,
        "seconds": payload["case"]["timeout_seconds"],
        "tool_calls": 0,
    }
    principal = {
        "principal_id": principal_id,
        "slot_id": "main",
        "role": "lead",
        "parent_principal_id": None,
        "parent_span_id": None,
        "span_id": "span-main",
        "provider": "fixture-provider",
        "model": "fixture-model",
        "model_revision": "fixture-revision",
        "prompt_id": "fixture-prompt",
        "skill_id": skill_id,
        "catalog_id": payload["treatment"]["base_catalog_id"],
        "tool_schema_id": "fixture-tools",
        "policy_id": "fixture-policy",
        "authority_id": payload["permission_policy"],
        "session_id": f"{envelope['run_id']}-main",
        "sandbox_id": f"{envelope['run_id']}-main",
        "worktree_id": envelope["entry_id"],
        "context_mode": "single",
        "inherited_context_digest": None,
        "untrusted_input_digest": None,
        "requested_budget": budget,
        "effective_budget": budget,
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:00Z",
        "status": "completed",
    }
    usage = {
        "pricing_identity": "fixture-pricing",
        "host_safety_review": {
            "capture_status": "captured",
            "host_safety_review_count": 1,
            "host_safety_review_latency_ms": 1,
        },
        "records": [{
            "principal_id": principal_id,
            "turn_id": turn["turn_id"],
            "phase": "execute",
            "call_id": "call-main",
            "input_tokens": 10,
            "output_tokens": 5,
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
    }
    emit(event)
    emit({
        "record_type": "skill-evaluator-host-result/2",
        "terminal": True,
        "terminal_status": "completed",
        "envelope": envelope,
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "principals": [principal],
        "handoffs": [],
        "actions": [],
        "artifacts": [],
        "state": [checkpoint],
        "cleanup": {"state": "not_applicable", "status": "clean"},
        "usage": usage,
        "context": context(),
        "assertions": [],
    })


def grade() -> None:
    checks = next(
        (
            argument.removeprefix("--checks=").split(",")
            for argument in sys.argv[1:]
            if argument.startswith("--checks=")
        ),
        ["outcome-check", "safety-check"],
    )
    emit({
        "overall_pass": True,
        "score": 100,
        "checks": [{
            "check_id": check_id,
            "pass": True,
            "evidence": [{
                "artifact": "result.json",
                "locator": {"start_line": 1, "end_line": 1},
                "observation": "synthetic host completed the fixture",
            }],
            "notes": "",
            "uncertainty": "",
        } for check_id in checks],
        "missing_evidence": [],
        "grader_failure": False,
        "grader_failure_reason": None,
    })


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        grade()
        return 0
    request = json.loads(line)
    if request["envelope"]["request_kind"] == "probe_capability":
        probe(request)
    else:
        execute(request)
    return 0


raise SystemExit(main())
