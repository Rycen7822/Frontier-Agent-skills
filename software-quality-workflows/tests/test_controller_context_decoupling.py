from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _closure import _set_phase  # noqa: E402
from _workflow_state import canonical_artifact_hash, canonical_hash  # noqa: E402
from advance_closure import ControllerConflict, initialize_workflow_from_handoff  # noqa: E402
from compute_frontier import compute_frontier  # noqa: E402
from project_context import project_context  # noqa: E402
from propagate_invalidation import propagate_invalidation  # noqa: E402


STATE_FIXTURE = ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json"


class ControllerContextDecouplingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = json.loads(STATE_FIXTURE.read_text(encoding="utf-8"))

    def test_state_schema_separates_controller_truth_from_context_trace(self) -> None:
        schema = json.loads((ROOT / "schemas" / "workflow-state.schema.json").read_text(encoding="utf-8"))
        owners = schema["$defs"]["active_owners"]
        self.assertNotIn("loaded_references", owners["properties"])
        self.assertNotIn("loaded_references", owners["required"])
        self.assertIn("context_trace_ref", schema["properties"])
        invariant = schema["$defs"]["invariant"]
        self.assertTrue({"locality", "targets"} <= set(invariant["required"]))
        self.assertEqual({"global", "node_set", "resource_set"}, set(invariant["properties"]["locality"]["enum"]))
        self.assertIn("effect_set", schema["$defs"]["node"]["required"])
        self.assertEqual(
            {"data", "control", "evidence", "invariant", "read", "write", "resource", "approval"},
            set(schema["$defs"]["edge"]["properties"]["kind"]["enum"]),
        )
        phases = set(schema["$defs"]["closure_run"]["properties"]["phase"]["enum"])
        self.assertFalse({"SPEC_COMPILING", "CONTRACT_FROZEN", "PLANNING"} & phases)
        self.assertEqual({"BASELINING", "VERIFIER_QUALIFYING", "SEARCHING", "SIGNING_OFF", "TERMINAL"}, phases)

    def test_context_trace_is_hash_excluded_rebuildable_and_phase_independent(self) -> None:
        state = deepcopy(self.state)
        state["active_owners"].pop("loaded_references", None)
        for invariant in state["global_invariants"]:
            invariant.update({"locality": "global", "targets": []})
        for node in state["nodes"]:
            node["effect_set"] = []
        state["context_trace_ref"] = "artifact:context-trace/trace-a"
        first_hash = canonical_hash(state)
        state["context_trace_ref"] = "artifact:context-trace/trace-b"
        self.assertEqual(first_hash, canonical_hash(state))
        owners_before = deepcopy(state["active_owners"])
        state["closure_run"] = {"phase": "SEARCHING"}
        _set_phase(state, "BASELINING")
        self.assertEqual(owners_before, state["active_owners"])
        self.assertEqual("artifact:context-trace/trace-b", state["context_trace_ref"])

        card_refs = [{"card_id": "sqw.entry.direct-change", "card_hash": "sha256:fadba67335939de220bafc50edd61b5a4743b262851fef59a5286beacd9725ec"}]
        projections = {"authority_projection": {"risk_ceiling": "local_reversible"}}
        text, metadata = project_context(state, budget_bytes=8192, card_refs=card_refs, artifact_projections=projections)
        state.pop("context_trace_ref")
        rebuilt, rebuilt_metadata = project_context(state, budget_bytes=8192, card_refs=card_refs, artifact_projections=projections)
        self.assertEqual(text, rebuilt)
        self.assertEqual(metadata["projection_hash"], rebuilt_metadata["projection_hash"])
        self.assertEqual(card_refs, metadata["card_refs"])
        self.assertEqual(["authority_projection"], metadata["artifact_projection_ids"])
        self.assertEqual(0, metadata["mandatory_truncation_count"])

    def test_invariant_locality_and_all_effect_conflicts_shape_frontier(self) -> None:
        state = deepcopy(self.state)
        state["active_owners"].pop("loaded_references", None)
        base = state["nodes"][1]
        base["effect_set"] = ["workspace:manifest"]
        peer = deepcopy(base)
        peer.update({"id": "N-03", "objective": "Independent peer", "read_set": ["docs/**"], "write_set": ["docs/**"], "resource_set": ["docs-runner"], "effect_set": ["workspace:docs"]})
        state["nodes"].append(peer)
        state["global_invariants"][0].update({"status": "changed", "locality": "node_set", "targets": ["N-02"]})
        localized = compute_frontier(state)
        self.assertEqual(["N-03"], localized["ready"])
        self.assertIn("invariant:I-01:changed", localized["blocked"]["N-02"])

        state["global_invariants"][0]["status"] = "current"
        base["read_set"] = ["shared/**"]
        peer["write_set"] = ["shared/**"]
        result = compute_frontier(state)
        self.assertEqual([["N-02"], ["N-03"]], result["parallel_batches"])
        self.assertIn("parallel-conflict:N-02:N-03", result["warnings"])

    def test_typed_local_invalidation_preserves_unrelated_branch_and_root_flags_escalate(self) -> None:
        state = deepcopy(self.state)
        state["global_invariants"][0].update({"locality": "node_set", "targets": ["N-02"]})
        unrelated = deepcopy(state["nodes"][1])
        unrelated.update({"id": "N-03", "objective": "Unrelated branch", "depends_on": [], "input_refs": [], "output_refs": [], "input_contracts": [], "output_contracts": [], "read_set": ["docs/**"], "write_set": ["docs/**"], "resource_set": ["docs"], "effect_set": [], "verifier_refs": []})
        state["nodes"].append(unrelated)
        local = propagate_invalidation(state, {"I-01"})
        self.assertEqual("local", local["repair_type"])
        self.assertIn("N-02", local["affected"])
        self.assertIn("N-03", local["preserved"])
        global_result = propagate_invalidation(state, {"N-02"}, escalation_flags={"hidden_shared_state"})
        self.assertEqual("global_or_parent_replan", global_result["repair_type"])
        self.assertIn("hidden_shared_state", global_result["escalation_reasons"])

    def test_event_schema_rejects_schema_valid_generic_noop(self) -> None:
        schema = json.loads((ROOT / "schemas" / "workflow-event.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        fixture_line = (ROOT / "tests" / "fixtures" / "workflow-events" / "valid-events.jsonl").read_text(encoding="utf-8").splitlines()[0]
        event = json.loads(fixture_line)
        event.update({"event_id": "evt-0001-candidate_evaluated", "type": "candidate_evaluated"})
        event["payload"].update({"summary": "no semantic fields", "artifact_refs": [], "changed_refs": [], "side_effects_observed": []})
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(event)))

    def test_initializer_binds_verified_handoff_and_starts_at_baselining(self) -> None:
        wp = ROOT.parent / "writing-plans"
        plan = json.loads((wp / "tests" / "fixtures" / "plan-state" / "valid-program.json").read_text(encoding="utf-8"))
        admission = json.loads((wp / "tests" / "fixtures" / "closure-contracts" / "valid-admission.json").read_text(encoding="utf-8"))
        authority = json.loads((wp / "tests" / "fixtures" / "closure-contracts" / "valid-authority-manifest.json").read_text(encoding="utf-8"))
        contract = json.loads((wp / "tests" / "fixtures" / "closure-contracts" / "valid-minimal.json").read_text(encoding="utf-8"))
        authority.update({"source_revision": plan["source"]["base_revision"], "scope_hash": plan["source"]["scope_hash"]})
        authority_hash = "sha256:" + sha256(json.dumps(authority, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        contract["authority_manifest_hash"] = authority_hash
        contract["source"].update(
            {
                "repository": plan["source"]["repository"],
                "base_revision": plan["source"]["base_revision"],
                "scope_hash": plan["source"]["scope_hash"],
                "policy_bundle_hash": plan["source"]["policy_bundle_hash"],
                "reference_manifest_hash": plan["source"]["reference_manifest_hash"],
            }
        )
        contract["scope"].update(
            {
                "scope_hash": plan["source"]["scope_hash"],
                "allowed_read_paths": plan["scope"]["allowed_reads"],
                "allowed_write_paths": plan["scope"]["allowed_writes"],
                "forbidden_paths": plan["scope"]["protected_paths"],
            }
        )
        contract.update({"status": "frozen", "frozen_at": "2026-07-15T00:00:00Z"})
        contract["content_hash"] = canonical_artifact_hash(contract)
        plan_hash = canonical_artifact_hash(plan)
        admission_hash = "sha256:" + sha256(json.dumps(admission, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        handoff = {
            "schema_version": "1.0",
            "handoff_id": "handoff-0123456789abcdefabcd",
            "bundle_id": plan["source"]["bundle_id"],
            "source_revision": plan["source"]["base_revision"],
            "execution_policy": "autonomous_closure",
            "profile": "program",
            "closure_admission_ref": contract["closure_admission_ref"],
            "closure_admission_hash": admission_hash,
            "plan_ref": "artifact:plan/plan-manifest-refresh-20260713",
            "plan_hash": plan_hash,
            "closure_contract_ref": "artifact:contract/CC-DEMO-001",
            "closure_contract_hash": contract["content_hash"],
            "authority_manifest_ref": contract["authority_manifest_ref"],
            "scope_hash": plan["source"]["scope_hash"],
            "frontier_node_ids": plan["current_frontier"],
            "required_execution_policy_ids": ["sqw.change.lifecycle", "sqw.verify.completion-evidence"],
            "unresolved_blockers": [],
        }
        state = initialize_workflow_from_handoff("wf-initialized", handoff, admission, plan, contract, authority)
        self.assertEqual("BASELINING", state["closure_run"]["phase"])
        self.assertEqual(handoff["plan_hash"], state["plan_ref"]["content_hash"])
        self.assertNotIn("loaded_references", state["active_owners"])
        self.assertNotIn("context_trace_ref", state)
        tampered = deepcopy(admission)
        tampered["decision"] = "DIRECT_SELECTED"
        with self.assertRaises(ControllerConflict):
            initialize_workflow_from_handoff("wf-rejected", handoff, tampered, plan, contract, authority)

        expanded_admission = deepcopy(admission)
        expanded_admission["unexpected"] = "must fail closed"
        expanded_admission_hash = "sha256:" + sha256(json.dumps(expanded_admission, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        admission_contract = deepcopy(contract)
        admission_contract["closure_admission_hash"] = expanded_admission_hash
        admission_contract["content_hash"] = canonical_artifact_hash(admission_contract)
        admission_handoff = deepcopy(handoff)
        admission_handoff.update({"closure_admission_hash": expanded_admission_hash, "closure_contract_hash": admission_contract["content_hash"]})
        with self.assertRaisesRegex(ControllerConflict, "admission-shape"):
            initialize_workflow_from_handoff("wf-expanded-admission", admission_handoff, expanded_admission, plan, admission_contract, authority)

        expanded_authority = deepcopy(authority)
        expanded_authority["unexpected"] = "must fail closed"
        expanded_authority_hash = "sha256:" + sha256(json.dumps(expanded_authority, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        authority_contract = deepcopy(contract)
        authority_contract["authority_manifest_hash"] = expanded_authority_hash
        authority_contract["content_hash"] = canonical_artifact_hash(authority_contract)
        authority_handoff = deepcopy(handoff)
        authority_handoff["closure_contract_hash"] = authority_contract["content_hash"]
        with self.assertRaisesRegex(ControllerConflict, "authority-manifest-shape"):
            initialize_workflow_from_handoff("wf-expanded-authority", authority_handoff, admission, plan, authority_contract, expanded_authority)


if __name__ == "__main__":
    unittest.main()
