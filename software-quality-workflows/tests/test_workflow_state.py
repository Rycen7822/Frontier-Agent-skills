from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import InputError, canonical_hash, load_json, load_json_lines  # noqa: E402
from validate_workflow_state import (  # noqa: E402
    validate_event_stream,
    validate_state,
    validate_transition,
)


STATE_FIXTURES = ROOT / "tests" / "fixtures" / "workflow-state"
EVENT_FIXTURES = ROOT / "tests" / "fixtures" / "workflow-events"
STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(ROOT / "schemas" / "workflow-event.schema.json")


def _base() -> dict:
    return load_json(STATE_FIXTURES / "valid-m2.json")


def _node(state: dict, node_id: str) -> dict:
    return next(item for item in state["nodes"] if item["id"] == node_id)


def _mutate(state: dict, name: str) -> dict:
    options: dict = {}
    if name == "schema_unknown_field":
        state["unknown"] = True
    elif name == "duplicate_id":
        state["artifacts"].append(deepcopy(state["artifacts"][0]))
    elif name == "missing_ref":
        _node(state, "N-02")["input_refs"] = ["EV-404"]
    elif name == "control_cycle":
        _node(state, "N-01")["depends_on"] = ["N-02"]
        state["edges"].append({"id": "X-04", "kind": "control", "from": "N-02", "to": "N-01"})
    elif name == "frontier_stale":
        state["frontier"] = ["N-01"]
    elif name == "done_without_evidence":
        _node(state, "N-02")["status"] = "done"
        state["frontier"] = []
    elif name == "scope_write":
        _node(state, "N-02")["write_set"] = ["/etc/passwd"]
    elif name == "authority_exceeded":
        _node(state, "N-02")["side_effect"] = "external_reversible"
    elif name == "approval_missing":
        state["authority"]["risk_ceiling"] = "external_reversible"
        state["authority"]["external_writes"] = "approved"
        _node(state, "N-02")["side_effect"] = "external_reversible"
    elif name == "retry_unsafe":
        state["authority"]["risk_ceiling"] = "external_non_idempotent"
        state["authority"]["external_writes"] = "approved"
        node = _node(state, "N-02")
        node["side_effect"] = "external_non_idempotent"
        node["attempt_policy"] = {"max_attempts": 2, "attempts_used": 0, "idempotency": "inspect_before_retry"}
    elif name == "sensitive_unclassified":
        state["artifacts"][0]["claim"] = "access_token=RAW_TOKEN_1234567890"
    elif name == "io_schema_mismatch":
        state["artifacts"][0]["schema_id"] = "sqw.other-result/1.0"
    elif name == "owner_duplicate":
        state["active_owners"]["companions"] = [state["active_owners"]["primary"]]
    elif name == "plan_ref_mismatch":
        _node(state, "N-02")["plan_node_ref"] = "plan:another-plan#P-02"
    elif name == "source_stale":
        options["current_revision"] = "different-revision"
    elif name == "plan_stale":
        options["current_plan_hash"] = "sha256:" + "9" * 64
    else:
        raise AssertionError(name)
    return options


class WorkflowStateTests(unittest.TestCase):
    def test_valid_m2_state_and_event_stream_are_accepted(self) -> None:
        self.assertEqual([], validate_state(_base(), STATE_SCHEMA))
        events = load_json_lines(EVENT_FIXTURES / "valid-events.jsonl")
        self.assertEqual([], validate_event_stream(events, EVENT_SCHEMA))

    def test_every_stable_state_violation_has_a_fixture(self) -> None:
        catalog = load_json(STATE_FIXTURES / "invalid-cases.json")
        self.assertEqual(14, len(catalog["cases"]))
        for case in catalog["cases"]:
            with self.subTest(case=case["id"]):
                state = _base()
                options = _mutate(state, case["mutation"])
                codes = {item.code for item in validate_state(state, STATE_SCHEMA, **options)}
                self.assertIn(case["expected_code"], codes, sorted(codes))

    def test_source_and_plan_hash_drift_are_distinct(self) -> None:
        source = _base()
        source_options = _mutate(source, "source_stale")
        self.assertIn("workflow.source-stale", {item.code for item in validate_state(source, STATE_SCHEMA, **source_options)})
        plan = _base()
        plan_options = _mutate(plan, "plan_stale")
        self.assertIn("workflow.plan-stale", {item.code for item in validate_state(plan, STATE_SCHEMA, **plan_options)})

    def test_scope_freshness_uses_v3_scope_binding_not_source_scope_hash(self) -> None:
        state = _base()
        binding_id = state["scope_binding"]["binding_id"]
        state["source"]["scope_hash"] = "sha256:" + "9" * 64
        self.assertNotIn("workflow.scope-stale", {item.code for item in validate_state(state, STATE_SCHEMA, current_scope_binding_id=binding_id)})
        self.assertIn("workflow.scope-stale", {item.code for item in validate_state(state, STATE_SCHEMA, current_scope_binding_id="sha256:" + "8" * 64)})

    def test_m0_and_retired_m1_are_schema_forbidden(self) -> None:
        m0 = _base()
        m0["mode"] = "M0_DIRECT"
        self.assertIn("workflow.schema", {item.code for item in validate_state(m0, STATE_SCHEMA)})
        m1 = _base()
        m1["mode"] = "M1_TRACE"
        self.assertIn("workflow.schema", {item.code for item in validate_state(m1, STATE_SCHEMA)})

    def test_materialized_completion_uses_locator_without_inline_payload(self) -> None:
        state = _base()
        state["card_completions"] = [{
            "storage": "materialized",
            "operation_id": "sha256:" + "1" * 64,
            "prior_state_version": 2,
            "prior_state_hash": "sha256:" + "2" * 64,
            "completion_id": "sha256:" + "3" * 64,
            "card_id": "sqw.test.behavior-cycle",
            "artifact_id": "test-behavior-cycle",
            "source_hash": state["source_identity"]["identity_hash"],
            "scope_binding_id": state["scope_binding"]["binding_id"],
            "content_locator": {
                "schema_version": "content-locator/1",
                "content_kind": "artifact",
                "artifact_id": "test-behavior-cycle",
                "content_hash": "sha256:" + "3" * 64,
                "bytes": 128,
            },
            "outcome": {"blocker": None, "decision_request": "sqw.select.verify.gate-selection-and-execution"},
        }]
        state["last_transition"] = {
            "transition_kind": "card",
            "operation_id": "sha256:" + "1" * 64,
            "prior_state_version": 2,
            "prior_state_hash": "sha256:" + "2" * 64,
            "completion_id": "sha256:" + "3" * 64,
            "next_decision_id": state["active_frontier"]["decision_id"],
        }
        state["state_hash"] = canonical_hash(state)
        self.assertEqual([], validate_state(state, STATE_SCHEMA))
        state["card_completions"][0]["completion"] = {"forbidden": "duplicate payload"}
        self.assertIn("workflow.schema", {item.code for item in validate_state(state, STATE_SCHEMA)})

    def test_baseline_failure_cannot_satisfy_done_node_evidence(self) -> None:
        state = _base()
        state["artifacts"][0]["observation"]["classification"] = "baseline_failure"
        self.assertIn("workflow.done-without-evidence", {item.code for item in validate_state(state, STATE_SCHEMA)})

    def test_sensitive_classification_does_not_allow_raw_credentials_in_state(self) -> None:
        state = _base()
        state["artifacts"][0]["sensitive"] = True
        state["artifacts"][0]["claim"] = "api_key=RAW_SECRET_1234567890"
        self.assertIn("workflow.sensitive-unclassified", {item.code for item in validate_state(state, STATE_SCHEMA)})

    def test_completion_rejects_pending_background_even_when_other_gates_pass(self) -> None:
        state = _base()
        _node(state, "N-02")["status"] = "skipped"
        state["frontier"] = []
        state["status"] = "completed"
        state["verifiers"][1]["status"] = "passed"
        state["pending_background"] = ["RUN-99"]
        self.assertIn("workflow.completion-premature", {item.code for item in validate_state(state, STATE_SCHEMA)})

    def test_transition_validator_rejects_skip_and_version_drift(self) -> None:
        previous = _base()
        current = deepcopy(previous)
        current["state_version"] += 1
        _node(current, "N-02")["status"] = "done"
        codes = {item.code for item in validate_transition(previous, current)}
        self.assertIn("workflow.status-transition", codes)
        current = deepcopy(previous)
        _node(current, "N-02")["status"] = "running"
        codes = {item.code for item in validate_transition(previous, current)}
        self.assertIn("workflow.state-version", codes)

    def test_worker_cannot_approve_or_complete_workflow(self) -> None:
        events = load_json_lines(EVENT_FIXTURES / "valid-events.jsonl")
        for event_type in ("node_completed", "approval_granted", "workflow_completed"):
            with self.subTest(event_type=event_type):
                event = deepcopy(events[1])
                event["event_id"] = "evt-000099"
                event["sequence"] = 99
                event["type"] = event_type
                if event_type == "approval_granted":
                    event["payload"]["approval_ref"] = "AP-SECURITY"
                codes = {item.code for item in validate_event_stream([event], EVENT_SCHEMA, require_contiguous=False)}
                self.assertIn("workflow.actor-forbidden", codes)

    def test_event_stream_rejects_duplicates_order_drift_and_workflow_mismatch(self) -> None:
        events = load_json_lines(EVENT_FIXTURES / "valid-events.jsonl")
        duplicate = deepcopy(events)
        duplicate[1]["event_id"] = duplicate[0]["event_id"]
        self.assertIn("workflow.event-duplicate", {item.code for item in validate_event_stream(duplicate, EVENT_SCHEMA)})
        out_of_order = deepcopy(events)
        out_of_order[2]["sequence"] = 7
        self.assertIn("workflow.event-order", {item.code for item in validate_event_stream(out_of_order, EVENT_SCHEMA)})
        wrong_start = deepcopy(events)
        wrong_start[0]["sequence"] = 2
        self.assertIn("workflow.event-order", {item.code for item in validate_event_stream(wrong_start, EVENT_SCHEMA)})
        wrong_workflow = deepcopy(events)
        wrong_workflow[-1]["workflow_id"] = "sqw-workflow:" + "b" * 64
        self.assertIn("workflow.event-workflow", {item.code for item in validate_event_stream(wrong_workflow, EVENT_SCHEMA)})
        stale_version = deepcopy(events)
        stale_version[-1]["state_version"] = 1
        self.assertIn("workflow.event-version", {item.code for item in validate_event_stream(stale_version, EVENT_SCHEMA)})

    def test_event_schema_and_sensitive_payload_fail_closed(self) -> None:
        event = load_json_lines(EVENT_FIXTURES / "valid-events.jsonl")[0]
        event["unexpected"] = True
        self.assertIn("workflow.event-schema", {item.code for item in validate_event_stream([event], EVENT_SCHEMA, require_contiguous=False)})
        event = load_json_lines(EVENT_FIXTURES / "valid-events.jsonl")[0]
        event["payload"]["summary"] = "password=UNCLASSIFIED_1234567890"
        self.assertIn("workflow.sensitive-unclassified", {item.code for item in validate_event_stream([event], EVENT_SCHEMA, require_contiguous=False)})

    def test_malformed_deep_and_oversized_inputs_fail_boundedly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "malformed.json"
            malformed.write_text('{"broken":', encoding="utf-8")
            with self.assertRaises(InputError):
                load_json(malformed)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaises(InputError):
                load_json(nonfinite)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"value":1,"value":2}', encoding="utf-8")
            with self.assertRaises(InputError):
                load_json(duplicate)
            deep = root / "deep.json"
            deep.write_text("[" * 45 + "0" + "]" * 45, encoding="utf-8")
            with self.assertRaises(InputError):
                load_json(deep)
            truncated = root / "events.jsonl"
            truncated.write_text('{"event_id":"evt-1"}\n{"broken":', encoding="utf-8")
            with self.assertRaises(InputError):
                load_json_lines(truncated)
            json_link = root / "state-link.json"
            json_link.symlink_to(malformed)
            with self.assertRaises(InputError):
                load_json(json_link)
            jsonl_link = root / "events-link.jsonl"
            jsonl_link.symlink_to(truncated)
            with self.assertRaises(InputError):
                load_json_lines(jsonl_link)
        state = _base()
        state["pending_background"] = [f"RUN-{index}" for index in range(1001)]
        self.assertIn("workflow.schema", {item.code for item in validate_state(state, STATE_SCHEMA)})


if __name__ == "__main__":
    unittest.main()
