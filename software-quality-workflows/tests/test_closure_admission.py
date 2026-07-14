from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from assess_closure_admission import assess_admission  # noqa: E402


BASE = {
    "autonomous_closure_requested": False,
    "intent_status": "defined",
    "machine_observable_outcome": True,
    "requirements_stable_enough": True,
    "known_requirement_conflict": False,
    "scope_freezable": True,
    "authority_freezable": True,
    "reproducible_environment": True,
    "verifier_separable": True,
    "bounded_side_effects": True,
    "resume_required": False,
    "expensive_proof_reusable": False,
    "local_repair_likely": False,
    "strategy_family_count": 1,
    "search_value": "none",
    "framework_tax": "low",
}


class ClosureAdmissionTests(unittest.TestCase):
    def test_routine_local_change_prefers_direct(self) -> None:
        result = assess_admission(BASE)
        self.assertEqual("direct_preferred", result["status"])
        self.assertEqual("change-execution", result["required_primary_owner"])
        self.assertEqual("M0_DIRECT", result["recommended_mode"])
        self.assertEqual([], result["missing_conditions"])

    def test_eligible_requires_all_safety_conditions_and_positive_value(self) -> None:
        facts = {**BASE, "autonomous_closure_requested": True, "resume_required": True}
        result = assess_admission(facts)
        self.assertEqual("closure_eligible", result["status"])
        self.assertEqual("autonomous-closure", result["required_primary_owner"])
        self.assertEqual("M2_SPARSE", result["recommended_mode"])
        self.assertIn("resume_required", result["reason_codes"])

    def test_request_never_overrides_observability_intent_or_authority(self) -> None:
        cases = (
            ("machine_observable_outcome", False, "spec_underdetermined"),
            ("requirements_stable_enough", False, "spec_underdetermined"),
            ("scope_freezable", False, "authority_blocked"),
            ("authority_freezable", False, "authority_blocked"),
            ("bounded_side_effects", False, "authority_blocked"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field):
                facts = {**BASE, "autonomous_closure_requested": True, "resume_required": True, field: value}
                result = assess_admission(facts)
                self.assertEqual(expected, result["status"])
                self.assertIn(field, result["missing_conditions"])

    def test_environment_and_verifier_have_distinct_non_success_results(self) -> None:
        environment = assess_admission({**BASE, "autonomous_closure_requested": True, "resume_required": True, "reproducible_environment": False})
        verifier = assess_admission({**BASE, "autonomous_closure_requested": True, "resume_required": True, "verifier_separable": False})
        self.assertEqual("environment_unavailable", environment["status"])
        self.assertEqual("verifier_unqualified_candidate", verifier["status"])
        self.assertIn("qualify_verifier", verifier["required_pre_freeze_actions"])

    def test_known_requirement_conflict_returns_spec_unsat(self) -> None:
        result = assess_admission({**BASE, "known_requirement_conflict": True})
        self.assertEqual("spec_unsat", result["status"])
        self.assertIn("emit_spec_unsat_certificate", result["required_pre_freeze_actions"])

    def test_material_ambiguity_and_null_safety_facts_fail_closed(self) -> None:
        ambiguity = assess_admission({**BASE, "intent_status": "materially_underdefined", "autonomous_closure_requested": True})
        self.assertEqual("spec_underdetermined", ambiguity["status"])
        for field in (
            "machine_observable_outcome",
            "scope_freezable",
            "authority_freezable",
            "reproducible_environment",
            "verifier_separable",
            "bounded_side_effects",
        ):
            with self.subTest(field=field):
                facts = {**BASE, "autonomous_closure_requested": True, "resume_required": True, field: None}
                result = assess_admission(facts)
                self.assertNotEqual("closure_eligible", result["status"])
                self.assertIn(field, result["missing_conditions"])

    def test_strategy_family_is_value_not_delegation_and_tax_can_prefer_direct(self) -> None:
        portfolio = assess_admission({**BASE, "strategy_family_count": 2, "search_value": "high"})
        self.assertEqual("closure_eligible", portfolio["status"])
        self.assertNotIn("delegation", portfolio["reason_codes"])
        no_search = assess_admission({**BASE, "strategy_family_count": 2, "search_value": "none"})
        self.assertEqual("direct_preferred", no_search["status"])
        taxed = assess_admission({**BASE, "autonomous_closure_requested": True, "framework_tax": "high", "search_value": "low"})
        self.assertEqual("direct_preferred", taxed["status"])

    def test_unknown_fields_types_and_cli_fail_boundedly(self) -> None:
        with self.assertRaises(ValueError):
            assess_admission({**BASE, "parallel_candidates": 2})
        with self.assertRaises(ValueError):
            assess_admission({**BASE, "strategy_family_count": True})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "facts.json"
            source.write_text(json.dumps({**BASE, "framework_tax": "mystery"}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "assess_closure_admission.py"), str(source)],
                capture_output=True,
                text=True,
                check=False,
                env={**dict(), "PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(2, result.returncode)
        self.assertIn('"ok": false', result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
