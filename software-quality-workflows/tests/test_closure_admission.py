from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


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
    "verifier_qualification_feasible": True,
    "bounded_side_effects": True,
    "resume_required": False,
    "expensive_proof_reusable": False,
    "local_repair_likely": False,
    "strategy_family_count": 1,
    "search_value": "none",
    "framework_tax": "low",
}
RESULT_KEYS = {
    "schema_version",
    "admission_id",
    "decision",
    "terminal_status",
    "reason_codes",
    "missing_conditions",
    "next_action",
    "recommended_execution_mode",
}


class ClosureAdmissionTests(unittest.TestCase):
    def test_direct_is_nonterminal_and_schema_exact(self) -> None:
        result = assess_admission(BASE)
        self.assertEqual(RESULT_KEYS, set(result))
        self.assertEqual(("DIRECT_SELECTED", "ROUTE_STANDARD", None, "M0_DIRECT"), (result["decision"], result["next_action"], result["terminal_status"], result["recommended_execution_mode"]))
        schema = json.loads((ROOT / "schemas" / "closure-admission.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(result)))

    def test_eligible_compiles_contract_before_workflow_creation(self) -> None:
        result = assess_admission({**BASE, "autonomous_closure_requested": True, "resume_required": True})
        self.assertEqual(("CLOSURE_ELIGIBLE", "COMPILE_CLOSURE_CONTRACT", None, "M2_SPARSE"), (result["decision"], result["next_action"], result["terminal_status"], result["recommended_execution_mode"]))
        self.assertIn("RESUME_REQUIRED", result["reason_codes"])
        self.assertNotIn("required_primary_owner", result)
        self.assertNotIn("required_pre_freeze_actions", result)

    def test_terminal_statuses_are_exact_and_only_disproved_verifier_is_terminal(self) -> None:
        cases = (
            ({"known_requirement_conflict": True}, "SPEC_UNSAT"),
            ({"intent_status": "materially_underdefined"}, "SPEC_UNDERDETERMINED"),
            ({"authority_freezable": False}, "AUTHORITY_BLOCKED"),
            ({"reproducible_environment": False}, "ENVIRONMENT_UNAVAILABLE"),
            ({"verifier_qualification_feasible": False}, "VERIFIER_UNQUALIFIABLE"),
            ({"bounded_side_effects": False}, "SIDE_EFFECT_UNBOUNDED"),
        )
        for overrides, terminal_status in cases:
            with self.subTest(terminal_status=terminal_status):
                result = assess_admission({**BASE, **overrides})
                self.assertEqual(("TERMINAL", "EMIT_TERMINAL", terminal_status), (result["decision"], result["next_action"], result["terminal_status"]))
        unresolved = assess_admission({**BASE, "verifier_qualification_feasible": None})
        self.assertEqual("DIRECT_SELECTED", unresolved["decision"])
        self.assertIn("verifier_qualification_feasible", unresolved["missing_conditions"])

    def test_input_and_cli_fail_boundedly_with_typed_codes(self) -> None:
        for payload, code in (({}, "ADMISSION_INPUT_INCOMPLETE"), ({**BASE, "parallel_candidates": 2}, "ADMISSION_INPUT_UNKNOWN_FIELD")):
            with self.subTest(code=code), self.assertRaises(ValueError) as caught:
                assess_admission(payload)
            self.assertEqual(code, caught.exception.code)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "facts.json"
            source.write_text(json.dumps({**BASE, "framework_tax": "mystery"}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "assess_closure_admission.py"), str(source)],
                capture_output=True,
                text=True,
                check=False,
                env={"PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(2, result.returncode)
        self.assertEqual("ADMISSION_INPUT_INVALID", json.loads(result.stdout)["error"]["code"])


if __name__ == "__main__":
    unittest.main()
