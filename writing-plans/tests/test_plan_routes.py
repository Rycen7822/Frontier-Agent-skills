from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from assess_plan_mode import assess  # noqa: E402


class PlanRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads((ROOT / "tests" / "fixtures" / "plan-route-cases.json").read_text(encoding="utf-8"))

    def test_all_frozen_routes_match(self) -> None:
        defaults = self.fixture["defaults"]
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                actual = assess({**defaults, **case["facts"]})
                expected = case["expected"]
                self.assertEqual(expected["route"], actual["route"])
                self.assertEqual(expected.get("profile"), actual["profile"])
                self.assertEqual(expected["execution_policy"], actual["execution_policy"])
                self.assertEqual(expected["reason_codes"], actual["reason_codes"])
                for field in ("primary_reference", "required_artifacts", "handoff_owner", "terminal_status"):
                    if field in expected:
                        self.assertEqual(expected[field], actual[field])
                self.assertTrue(set(expected.get("required_references", [])).issubset(actual["required_references"]))
                self.assertTrue(set(expected.get("must_not_load", [])).issubset(actual["must_not_load"]))
                for reference in actual["required_references"] + actual["optional_references"]:
                    self.assertIn("/", reference, f"reference must be a reachable path: {reference}")

    def test_strategy_families_and_write_slices_are_not_conflated(self) -> None:
        cases = {case["id"]: case for case in self.fixture["cases"]}
        strategies = assess({**self.fixture["defaults"], **cases["two_strategy_families_one_write_slice"]["facts"]})
        slices = assess({**self.fixture["defaults"], **cases["one_strategy_three_write_slices"]["facts"]})
        self.assertEqual("program", strategies["profile"])
        self.assertNotIn("independent_write_slices", strategies["reason_codes"])
        self.assertEqual("handoff", slices["profile"])
        self.assertNotIn("multiple_strategy_families", slices["reason_codes"])

    def test_program_references_are_loaded_only_by_concrete_trigger(self) -> None:
        defaults = self.fixture["defaults"]
        core = {
            "references/plan-profiles.md",
            "references/plan-state-contract.md",
            "references/implementation-slicing-and-context-capsules.md",
        }
        resumed = assess({**defaults, "resume_required": True})
        self.assertEqual(core, set(resumed["required_references"]))
        self.assertNotIn("references/deprecation-migration-plans.md", resumed["required_references"])
        self.assertNotIn("references/architecture-decision-records.md", resumed["required_references"])

        migration = assess({**defaults, "migration_or_rollback": True})
        self.assertTrue(core <= set(migration["required_references"]))
        self.assertIn("references/deprecation-migration-plans.md", migration["required_references"])
        self.assertNotIn("references/architecture-decision-records.md", migration["required_references"])

        public = assess({**defaults, "public_contract": True})
        self.assertTrue(core <= set(public["required_references"]))
        self.assertIn("references/architecture-decision-records.md", public["required_references"])
        self.assertNotIn("references/deprecation-migration-plans.md", public["required_references"])

    def test_cli_rejects_unknown_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            source.write_text(json.dumps({"unexpected_complexity_score": 9}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "assess_plan_mode.py"), str(source)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(2, result.returncode)
        self.assertIn("unknown route facts", result.stdout)

    def test_cli_rejects_invalid_tristate_and_counts(self) -> None:
        for payload in (
            {"root_cause_status": "probably"},
            {"public_contract": "false"},
            {"independent_write_slices": -1},
            {"strategy_family_count": 0},
        ):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "input.json"
                source.write_text(json.dumps(payload), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPTS / "assess_plan_mode.py"), str(source)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(2, result.returncode)

    def test_closure_eligible_never_treats_unknown_trigger_as_false(self) -> None:
        defaults = self.fixture["defaults"]
        for field in ("public_contract", "migration_or_rollback", "external_side_effect", "long_corpus_only", "disposable_spike"):
            with self.subTest(field=field):
                result = assess({**defaults, "autonomous_closure_admission": "eligible", field: None})
                self.assertEqual("terminal", result["route"])
                self.assertEqual("insufficient_route_facts", result["terminal_status"])

    def test_reference_budget_exceptions_name_every_reference_over_five(self) -> None:
        result = assess(
            {
                **self.fixture["defaults"],
                "autonomous_closure_admission": "eligible",
                "public_contract": True,
                "migration_or_rollback": True,
                "strategy_family_count": 2,
            }
        )
        overflow = result["required_references"][5:]
        self.assertGreaterEqual(len(overflow), 1)
        self.assertEqual(
            [f"reference_budget_exception:{reference}" for reference in overflow],
            [reason for reason in result["reason_codes"] if reason.startswith("reference_budget_exception:")],
        )

    def test_profile_templates_are_bounded_projections(self) -> None:
        templates = ROOT / "templates"
        brief = (templates / "brief-change-card.md").read_text(encoding="utf-8")
        handoff = (templates / "executable-handoff.md").read_text(encoding="utf-8")
        program = (templates / "program-migration-map.md").read_text(encoding="utf-8")
        self.assertIn("Outcome:", brief)
        self.assertNotIn("commit", brief.lower())
        self.assertIn("Current frontier", handoff)
        self.assertIn("Gaps/fog", handoff)
        self.assertIn("State ref", program)
        self.assertIn("Rollout and rollback", program)
        self.assertIn("not yet specified", program)

    def test_removed_compatibility_surface_is_absent(self) -> None:
        removed_paths = {
            "references/compatibility-map.json",
            "references/context-compaction-resistant-upgrade-plans.md",
            "references/evidence-backed-standalone-roadmaps.md",
            "references/fillable-requirements-glossary-pattern.md",
            "references/legacy-manifest-diff-compatibility.md",
            "references/local-artifact-cleanup-and-benchmark-fixture-expansion.md",
            "references/plan-absorbed-skill.md",
            "references/research-reference-materials.md",
            "references/result-preserving-optimization-plans.md",
            "references/spike-absorbed-skill.md",
            "scripts/migrate_legacy_plan_ids.py",
            "scripts/validate_compatibility_stubs.py",
        }
        for relative in sorted(removed_paths):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
