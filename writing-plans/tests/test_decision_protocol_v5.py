from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from assess_plan_mode import assess  # noqa: E402


TARGET_CARDS = {
    "wp.profiles.brief",
    "wp.profiles.handoff",
    "wp.profiles.program",
    "wp.experiments.disposable-spike",
    "wp.bridges.long-document-handoff",
    "wp.migration.deprecation-and-rollout",
    "wp.slicing.context-capsules",
    "wp.slicing.outcome-slices",
    "wp.design.decision-resolution",
    "wp.economy.output-projection",
}
FACT_KEYS = {
    "schema_version",
    "explicit_plan_request",
    "root_cause_status",
    "intent_status",
    "copy_paste_projection_requested",
    "disposable_spike",
    "durable_handoff",
    "external_side_effect",
    "independent_write_slices",
    "long_corpus_only",
    "migration_or_rollback",
    "public_contract",
    "resume_required",
    "same_session_execution",
    "strategy_family_count",
    "pending_decision_ids",
    "available_artifact_ids",
    "completed_decision_ids",
    "just_completed_card_id",
    "decision_request",
}
RESULT_KEYS = {
    "schema_version",
    "route_action",
    "route_owner",
    "selected_decision_id",
    "primary_card",
    "required_artifact_ids",
    "reason_codes",
}
MAPPING_KEYS = {
    "decision_id",
    "card_id",
    "priority",
    "required_artifact_ids",
    "produced_artifact_ids",
    "positive_fixture_id",
    "near_miss_fixture_id",
}
MANIFEST_CARD_KEYS = {
    "bytes", "card_id", "card_version", "decision_id", "kind", "max_bytes", "path",
    "required_artifact_ids", "produced_artifact_ids", "sha256",
}
class WritingDecisionProtocolV5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "decision-route-cases-v5.json").read_text(encoding="utf-8")
        )

    def _load(self, relative: str) -> object:
        path = ROOT / relative
        self.assertTrue(path.is_file(), f"missing target contract: {relative}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.fail(f"invalid JSON in {relative}: {exc}")

    def _assess(self, overlay: dict[str, object]) -> dict[str, object]:
        try:
            return assess({**self.fixture["defaults"], **overlay})
        except Exception as exc:  # RED converts the legacy protocol rejection into one assertion failure.
            self.fail(f"target route facts were rejected: {type(exc).__name__}: {exc}")

    def test_v2_route_and_decision_map_schemas_are_closed(self) -> None:
        facts_schema = self._load("schemas/plan-route-facts.schema.json")
        result_schema = self._load("schemas/plan-route-result.schema.json")
        map_schema = self._load("schemas/decision-card-map.schema.json")
        for schema in (facts_schema, result_schema, map_schema):
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])
        self.assertEqual(FACT_KEYS, set(facts_schema["properties"]))
        self.assertEqual(RESULT_KEYS, set(result_schema["properties"]))
        self.assertEqual("2.0", facts_schema["properties"]["schema_version"]["const"])
        self.assertEqual("2.0", result_schema["properties"]["schema_version"]["const"])
        mapping_schema = map_schema["properties"]["decisions"]["items"]
        self.assertEqual(MAPPING_KEYS, set(mapping_schema["properties"]))
        self.assertEqual(MAPPING_KEYS, set(mapping_schema["required"]))

    def test_exact_inventory_mapping_and_selector_fixtures(self) -> None:
        manifest = self._load("registries/reference-cards.manifest.json")
        decision_map = self._load("registries/decision-card-map.json")
        cards = manifest["cards"]
        mappings = decision_map["decisions"]
        self.assertEqual("5.0.0", manifest["skill_version"])
        self.assertEqual(TARGET_CARDS, {card["card_id"] for card in cards})
        self.assertEqual(TARGET_CARDS, {mapping["card_id"] for mapping in mappings})
        self.assertEqual(len(mappings), len({mapping["decision_id"] for mapping in mappings}))
        self.assertEqual(len(mappings), len({mapping["card_id"] for mapping in mappings}))
        self.assertEqual(len(mappings), len({mapping["priority"] for mapping in mappings}))
        positive_ids = {case["id"] for case in self.fixture["positive_cases"]}
        near_miss_ids = {case["id"] for case in self.fixture["near_miss_cases"]}
        self.assertEqual({mapping["positive_fixture_id"] for mapping in mappings}, positive_ids)
        self.assertEqual({mapping["near_miss_fixture_id"] for mapping in mappings}, near_miss_ids)
        for card in cards:
            self.assertEqual(MANIFEST_CARD_KEYS, set(card))
            mapping = next(item for item in mappings if item["card_id"] == card["card_id"])
            self.assertEqual(mapping["decision_id"], card["decision_id"])
            self.assertEqual(mapping["required_artifact_ids"], card["required_artifact_ids"])
            self.assertEqual(mapping["produced_artifact_ids"], card["produced_artifact_ids"])

    def test_unknown_duplicate_completed_unmet_and_wrong_producer_block(self) -> None:
        for case in self.fixture["negative_cases"]:
            with self.subTest(case=case["id"]):
                result = self._assess(case["facts"])
                self.assertEqual(RESULT_KEYS, set(result))
                self.assertEqual("blocked", result["route_action"])
                self.assertIsNone(result["selected_decision_id"])
                self.assertIsNone(result["primary_card"])
                self.assertEqual(case["expected_reason"], result["reason_codes"][0])

    def test_every_positive_and_near_miss_selector_is_executable(self) -> None:
        for case in self.fixture["positive_cases"]:
            with self.subTest(case=case["id"]):
                result = self._assess(case["facts"])
                self.assertIsNotNone(result["primary_card"], result)
                self.assertEqual((case["decision_id"], case["expected_card_id"]), (
                    result["selected_decision_id"], result["primary_card"]["card_id"],
                ))
        for case in self.fixture["near_miss_cases"]:
            with self.subTest(case=case["id"]):
                result = self._assess(case["facts"])
                self.assertIsNotNone(result["primary_card"], result)
                self.assertEqual(case["expected_decision_id"], result["selected_decision_id"])
                self.assertNotEqual(case["excluded_card_id"], result["primary_card"]["card_id"])

    def test_multi_step_sequence_and_precedence_are_deterministic(self) -> None:
        for sequence in self.fixture["sequence_cases"]:
            for step in sequence["steps"]:
                with self.subTest(sequence=sequence["id"], decision=step["expected_decision_id"]):
                    result = self._assess(step["facts"])
                    self.assertEqual("select_card", result["route_action"])
                    self.assertEqual(step["expected_decision_id"], result["selected_decision_id"])
                    self.assertEqual(step["expected_card_id"], result["primary_card"]["card_id"])
        diagnosis = self._assess(
            {"root_cause_status": "unknown", "pending_decision_ids": ["wp.select.economy.output-projection"]}
        )
        self.assertEqual(("handoff", "software-quality-workflows"), (diagnosis["route_action"], diagnosis["route_owner"]))
        self.assertIsNone(diagnosis["selected_decision_id"])


if __name__ == "__main__":
    unittest.main()
