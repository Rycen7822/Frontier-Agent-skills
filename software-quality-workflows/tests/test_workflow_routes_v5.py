from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from route_workflow import assess, validate_route_result  # noqa: E402


SURFACE_FAMILIES = [
    "public_contract",
    "data_state",
    "security_privacy",
    "runtime_platform",
    "dependency_supply_chain",
    "browser_ui",
    "performance_resource",
    "plugin_installed_surface",
    "migration_release",
    "workspace_vcs",
    "external_side_effect",
    "test_fixture_benchmark",
    "observability_operations",
    "concurrency_shared_state",
]
BASE = {
    "schema_version": "1.0",
    "request_mode": "change",
    "intent_status": "adequate",
    "root_cause_status": "not_applicable",
    "implicated_surfaces": [],
    "unknown_implicated_facts": [],
    "surface_assessment": {
        "taxonomy_version": "sqw-route-surfaces/1",
        "coverage": "complete",
        "assessed_families": SURFACE_FAMILIES,
        "evidence_refs": ["request:current", "repo:surface-inventory@sha256:abc"],
    },
    "persistence_need": "none",
    "delegation_need": "none",
    "external_side_effect": "none",
    "explicit_autonomous_closure": False,
}
RESULT_KEYS = {
    "schema_version",
    "route_action",
    "workflow_mode",
    "execution_policy",
    "selection_stage",
    "selected_decision_id",
    "primary_owner_id",
    "primary_card",
    "fact_projection",
    "required_artifact_projection_ids",
    "reason_codes",
    "admission_ref",
}


class WorkflowRouteV5Tests(unittest.TestCase):
    def assert_exact_valid(self, result: dict[str, object]) -> None:
        self.assertEqual(RESULT_KEYS, set(result))
        self.assertEqual([], validate_route_result(result, ROOT))
        self.assertNotIn("required_references", result)
        self.assertNotIn("active_normative_owners", result)

    def test_empty_is_typed_incomplete_and_minimal_routine_is_one_exact_card(self) -> None:
        with self.assertRaises(ValueError) as caught:
            assess({})
        self.assertEqual("ROUTE_INPUT_INCOMPLETE", getattr(caught.exception, "code", None))

        result = assess(BASE)
        self.assert_exact_valid(result)
        self.assertEqual(("EXECUTE", "M0_DIRECT", "standard"), (result["route_action"], result["workflow_mode"], result["execution_policy"]))
        self.assertEqual("sqw.entry.direct-change", result["primary_card"]["card_id"])
        self.assertEqual({"card_id", "path", "sha256", "bytes"}, set(result["primary_card"]))
        for schema_name, instance in (("route-facts.schema.json", BASE), ("route-result.schema.json", result)):
            schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(instance)))

    def test_assessment_coverage_and_implicated_unknowns_fail_closed(self) -> None:
        incomplete = deepcopy(BASE)
        incomplete["surface_assessment"]["assessed_families"] = SURFACE_FAMILIES[:-1]
        for payload, code in (
            (incomplete, "ROUTE_FACTS_INCOMPLETE"),
            ({**BASE, "implicated_surfaces": ["public_contract"], "unknown_implicated_facts": ["public_contract.compatibility"]}, "IMPLICATED_FACT_UNKNOWN"),
        ):
            with self.subTest(code=code), self.assertRaises(ValueError) as caught:
                assess(payload)
            self.assertEqual(code, getattr(caught.exception, "code", None))

    def test_selection_precedence_stops_at_recovery_diagnosis_intent_and_audit(self) -> None:
        cases = (
            ({"request_mode": "recovery", "root_cause_status": "unknown"}, "sqw.entry.recovery"),
            ({"root_cause_status": "unknown", "explicit_autonomous_closure": True}, "sqw.entry.diagnose-failure"),
            ({"intent_status": "materially_underdefined", "explicit_autonomous_closure": True}, "sqw.entry.intent-discovery"),
            ({"request_mode": "report"}, "sqw.entry.read-only-audit"),
            ({"request_mode": "review"}, "sqw.review.tier-selection"),
        )
        for overrides, card_id in cases:
            with self.subTest(card_id=card_id):
                result = assess({**BASE, **overrides})
                self.assert_exact_valid(result)
                self.assertEqual(card_id, result["primary_card"]["card_id"])

    def test_closure_is_preworkflow_and_does_not_select_mode_owner_or_card(self) -> None:
        result = assess({**BASE, "explicit_autonomous_closure": True})
        self.assert_exact_valid(result)
        self.assertEqual("ASSESS_CLOSURE", result["route_action"])
        self.assertIsNone(result["workflow_mode"])
        self.assertIsNone(result["execution_policy"])
        self.assertIsNone(result["primary_owner_id"])
        self.assertIsNone(result["primary_card"])

    def test_unauthorized_external_effect_emits_terminal_without_workflow(self) -> None:
        result = assess(
            {
                **BASE,
                "external_side_effect": "unauthorized",
                "implicated_surfaces": ["external_side_effect"],
            }
        )
        self.assert_exact_valid(result)
        self.assertEqual("EMIT_TERMINAL", result["route_action"])
        self.assertIsNone(result["workflow_mode"])
        self.assertIsNone(result["primary_card"])
        self.assertIn("EXTERNAL_SIDE_EFFECT_UNAUTHORIZED", result["reason_codes"])

    def test_exact_result_rejects_extra_fields_and_nonmanifest_card_identity(self) -> None:
        valid = assess(BASE)
        extra = {**valid, "required_references": ["references/entry/direct-change.md"]}
        self.assertIn("route.shape", {item.code for item in validate_route_result(extra, ROOT)})
        stale = deepcopy(valid)
        stale["primary_card"]["sha256"] = "sha256:" + "0" * 64
        self.assertIn("route.card-identity", {item.code for item in validate_route_result(stale, ROOT)})
        closure = assess({**BASE, "explicit_autonomous_closure": True})
        fake_workflow = {**closure, "workflow_mode": "M2_SPARSE"}
        self.assertIn("route.closure-assessment", {item.code for item in validate_route_result(fake_workflow, ROOT)})


if __name__ == "__main__":
    unittest.main()
