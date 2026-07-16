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

from assess_plan_mode import RESULT_KEYS, assess, validate_plan_route_result  # noqa: E402


class PlanRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads((ROOT / "tests" / "fixtures" / "plan-route-cases.json").read_text(encoding="utf-8"))

    def test_all_sparse_frozen_routes_select_zero_or_one_exact_card(self) -> None:
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                actual = assess({**self.fixture["defaults"], **case["facts"]})
                self.assertEqual(RESULT_KEYS, set(actual))
                self.assertEqual([], validate_plan_route_result(actual, ROOT))
                self.assertNotIn("required_references", actual)
                for key, expected in case["expected"].items():
                    if key == "primary_card_id":
                        observed = actual["primary_card"]["card_id"] if actual["primary_card"] else None
                    else:
                        observed = actual[key]
                    self.assertEqual(expected, observed, (key, actual))

    def test_route_fact_and_result_schemas_are_strict(self) -> None:
        facts = self.fixture["defaults"]
        result = assess(facts)
        for schema_name, instance in (("plan-route-facts.schema.json", facts), ("plan-route-result.schema.json", result)):
            schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(instance)))
        self.assertTrue(validate_plan_route_result({**result, "required_references": []}, ROOT))
        brief = assess({**facts, "explicit_plan_request": True})
        wrong_profile = {**brief, "profile": "program"}
        self.assertIn("plan-route.local-selection", {item.code for item in validate_plan_route_result(wrong_profile, ROOT)})

    def test_strategy_families_and_write_slices_remain_distinct(self) -> None:
        defaults = self.fixture["defaults"]
        strategies = assess({**defaults, "closure_admission_decision": "CLOSURE_ELIGIBLE", "strategy_family_count": 2})
        slices = assess({**defaults, "independent_write_slices": 3})
        self.assertEqual(("program", "wp.closure.compile"), (strategies["profile"], strategies["primary_card"]["card_id"]))
        self.assertNotIn("INDEPENDENT_WRITE_SLICES", strategies["reason_codes"])
        self.assertEqual(("handoff", "wp.profiles.handoff"), (slices["profile"], slices["primary_card"]["card_id"]))
        self.assertNotIn("MULTIPLE_STRATEGY_FAMILIES", slices["reason_codes"])

    def test_external_bridge_and_spike_select_exact_current_cards(self) -> None:
        defaults = self.fixture["defaults"]
        spike = assess({**defaults, "disposable_spike": True})
        bridge = assess({**defaults, "long_corpus_only": True})
        self.assertEqual(
            ("wp.experiments.disposable-spike", "references/experiments/disposable-spike.md"),
            (spike["primary_card"]["card_id"], spike["primary_card"]["path"]),
        )
        self.assertEqual(
            ("wp.bridges.long-document-handoff", "references/bridges/long-document-handoff.md"),
            (bridge["primary_card"]["card_id"], bridge["primary_card"]["path"]),
        )

    def test_cli_rejects_empty_unknown_invalid_tristate_and_counts(self) -> None:
        payloads = (
            ({}, "PLAN_ROUTE_INPUT_INCOMPLETE"),
            ({**self.fixture["defaults"], "unexpected_complexity_score": 9}, "PLAN_ROUTE_INPUT_UNKNOWN_FIELD"),
            ({**self.fixture["defaults"], "root_cause_status": "probably"}, "PLAN_ROUTE_INPUT_INVALID"),
            ({**self.fixture["defaults"], "independent_write_slices": -1}, "PLAN_ROUTE_INPUT_INVALID"),
        )
        for payload, code in payloads:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "input.json"
                source.write_text(json.dumps(payload), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "-B", str(SCRIPTS / "assess_plan_mode.py"), str(source)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            self.assertEqual(2, result.returncode)
            self.assertEqual(code, json.loads(result.stdout)["error"]["code"])

    def test_profile_templates_remain_bounded_projections(self) -> None:
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
