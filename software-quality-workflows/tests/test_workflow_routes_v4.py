from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from route_workflow import assess, validate_route_result  # noqa: E402


BASE = {
    "request_mode": "change",
    "task_kind": "routine_change",
    "root_cause_status": "not_applicable",
    "intent_status": "defined",
    "same_session": True,
    "durable_handoff": False,
    "resume_required": False,
    "independent_read_slices": 0,
    "independent_write_slices": 0,
    "strategy_family_count": 1,
    "writes_are_disjoint": False,
    "resources_are_disjoint": False,
    "machine_observable_outcome": True,
    "requirements_stable_enough": True,
    "verifier_separable": True,
    "reproducible_environment": True,
    "bounded_side_effects": True,
    "search_value": "none",
    "dirty_or_concurrent_work": False,
    "public_contract": False,
    "security_boundary": False,
    "migration_or_release": False,
    "installed_surface": False,
    "external_side_effect": False,
    "destructive_or_irreversible": False,
    "privileged": False,
    "shared_mutable_state": False,
    "source_version_uncertain": False,
    "verification_cost": "low",
    "failure_locality": "likely_local",
    "explicit_plan_request": False,
    "autonomous_closure_requested": False,
    "trace_only": False,
    "plugin_source": False,
    "browser_runtime": False,
    "performance_sensitive": False,
    "slow_external_job": False,
    "publication_ceiling": "none",
    "user_constraints": {
        "no_subagents": False,
        "no_external_writes": True,
        "max_review_rounds": 2,
        "max_candidate_evaluations": 10,
    },
}


class WorkflowRouteV4Tests(unittest.TestCase):
    def assert_valid(self, result: dict[str, object]) -> None:
        self.assertEqual([], validate_route_result(result, ROOT))
        for path in result["required_references"]:
            self.assertTrue(str(path).startswith("references/"), path)

    def test_routine_and_trace_use_real_change_owner_with_standard_policy(self) -> None:
        direct = assess(BASE)
        trace = assess({**BASE, "trace_only": True})
        self.assertEqual(("M0_DIRECT", "standard", "change-execution"), (direct["workflow_mode"], direct["execution_policy"], direct["primary_owner"]))
        self.assertEqual("not_applicable", direct["closure_admission"])
        self.assertIn("references/change-execution.md", direct["required_references"])
        self.assertEqual("M1_TRACE", trace["workflow_mode"])
        self.assertEqual(direct["primary_owner"], trace["primary_owner"])
        self.assertEqual(direct["required_gates"], trace["required_gates"])
        self.assert_valid(direct)
        self.assert_valid(trace)

    def test_diagnosis_and_material_intent_precede_closure(self) -> None:
        diagnosis = assess({**BASE, "task_kind": "bugfix", "root_cause_status": "unknown", "autonomous_closure_requested": True})
        ambiguity = assess({**BASE, "intent_status": "materially_underdefined", "autonomous_closure_requested": True})
        self.assertEqual("systematic-debugging", diagnosis["primary_owner"])
        self.assertEqual("standard", diagnosis["execution_policy"])
        self.assertEqual("intent-and-design-discovery", ambiguity["primary_owner"])
        self.assertEqual("terminal", ambiguity["closure_admission"])

    def test_eligible_closure_is_program_and_never_m0_or_m1(self) -> None:
        result = assess({**BASE, "autonomous_closure_requested": True, "resume_required": True})
        self.assertEqual("autonomous_closure", result["execution_policy"])
        self.assertEqual("eligible", result["closure_admission"])
        self.assertEqual("autonomous-closure", result["primary_owner"])
        self.assertIn(result["workflow_mode"], {"M2_SPARSE", "M3_FULL"})
        self.assertEqual("program", result["plan_profile"])
        self.assertIn("references/autonomous-closure.md", result["required_references"])
        self.assertTrue({"authority-and-scope", "workflow-state-contract", "verifier-kernel"}.issubset(result["active_normative_owners"]))
        self.assert_valid(result)

    def test_requested_closure_can_fall_back_or_terminal_without_fake_workflow(self) -> None:
        fallback = assess({**BASE, "autonomous_closure_requested": True})
        terminal = assess({**BASE, "autonomous_closure_requested": True, "resume_required": True, "reproducible_environment": False})
        self.assertEqual(("standard", "ineligible", "change-execution"), (fallback["execution_policy"], fallback["closure_admission"], fallback["primary_owner"]))
        self.assertEqual("terminal", terminal["closure_admission"])
        self.assertFalse(terminal["durable_state_required"])
        self.assertNotEqual("closure_eligible", terminal.get("admission_status"))

    def test_strategy_families_and_independent_slices_are_separate(self) -> None:
        strategies = assess({**BASE, "strategy_family_count": 2, "search_value": "high"})
        slices = assess({**BASE, "independent_write_slices": 3, "writes_are_disjoint": True, "resources_are_disjoint": True, "durable_handoff": True})
        reads = assess({**BASE, "request_mode": "report", "task_kind": "audit", "independent_read_slices": 3, "durable_handoff": True})
        self.assertEqual([], strategies["active_companions"])
        self.assertNotIn("delegation_net_positive", strategies["reason_codes"])
        self.assertIn("delegated-development", slices["active_normative_owners"])
        self.assertNotIn("evidence-delegation", slices["active_companions"])
        self.assertEqual("change-execution", slices["primary_owner"])
        self.assertIn("evidence-delegation", reads["active_companions"])
        no_search = assess({**BASE, "strategy_family_count": 2, "search_value": "none"})
        self.assertEqual("standard", no_search["execution_policy"])
        self.assertEqual("change-execution", no_search["primary_owner"])

    def test_null_safety_facts_and_user_constraints_fail_closed(self) -> None:
        unknown = assess({**BASE, "security_boundary": None})
        self.assertEqual("M2_SPARSE", unknown["workflow_mode"])
        self.assertEqual("standard", unknown["execution_policy"])
        self.assertIn("risk_fact_unknown", unknown["reason_codes"])
        constrained = assess({**BASE, "user_constraints": {**BASE["user_constraints"], "no_subagents": True}})
        self.assertIn("references/delegated-development.md", constrained["must_not_load"])
        self.assertIn("delegation", constrained["forbidden_actions"])
        unknown_outcome = assess({**BASE, "machine_observable_outcome": None})
        self.assertEqual("M2_SPARSE", unknown_outcome["workflow_mode"])
        self.assertIn("risk_fact_unknown", unknown_outcome["reason_codes"])

    def test_public_migration_stays_standard_when_admission_has_no_value(self) -> None:
        result = assess({**BASE, "task_kind": "migration", "public_contract": True, "migration_or_release": True})
        self.assertEqual(("M3_FULL", "standard", "change-execution"), (result["workflow_mode"], result["execution_policy"], result["primary_owner"]))
        self.assertEqual("program", result["plan_profile"])
        self.assertIn("references/api-interface-design.md", result["required_references"])

    def test_route_result_rejects_virtual_owner_unregistered_path_and_budget_overflow(self) -> None:
        valid = assess(BASE)
        virtual = {**valid, "primary_owner": "direct-change"}
        wrong_path = {**valid, "required_references": ["change-execution"]}
        too_many = {**valid, "active_normative_owners": ["authority-and-scope"] * 9}
        self.assertIn("route.owner-unknown", {item.code for item in validate_route_result(virtual, ROOT)})
        self.assertIn("route.reference-path", {item.code for item in validate_route_result(wrong_path, ROOT)})
        self.assertIn("route.owner-budget", {item.code for item in validate_route_result(too_many, ROOT)})
        forbidden_required = {**valid, "must_not_load": ["references/change-execution.md"]}
        self.assertIn("route.reference-conflict", {item.code for item in validate_route_result(forbidden_required, ROOT)})
        malformed = {**valid, "active_normative_owners": [{}], "closure_admission": "mystery", "durable_state_required": "yes"}
        codes = {item.code for item in validate_route_result(malformed, ROOT)}
        self.assertTrue({"route.owner-budget", "route.closure-admission", "route.durable-state"}.issubset(codes))
        unknown_field = {**valid, "silent_policy": True}
        self.assertIn("route.shape", {item.code for item in validate_route_result(unknown_field, ROOT)})


if __name__ == "__main__":
    unittest.main()
