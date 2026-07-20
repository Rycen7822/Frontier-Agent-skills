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

from route_workflow import assess  # noqa: E402


TARGET_CARDS = {
    "sqw.entry.direct-change", "sqw.entry.diagnose-failure", "sqw.entry.intent-discovery",
    "sqw.entry.read-only-audit", "sqw.entry.recovery",
    "sqw.control.scope-authority-and-effects", "sqw.control.evidence-and-verifier-integrity",
    "sqw.diagnosis.evidence-and-hypothesis", "sqw.intent.discovery-and-freeze",
    "sqw.test.behavior-cycle", "sqw.test.oracle-and-lifecycle",
    "sqw.verify.gate-selection-and-execution", "sqw.verify.classification-and-completion",
    "sqw.domain.api.contract-and-migration",
    "sqw.domain.architecture.boundaries-and-alternatives", "sqw.domain.architecture.migration-proof",
    "sqw.domain.browser.evidence-and-readiness", "sqw.domain.browser.content-security",
    "sqw.domain.observability.signal-and-recovery", "sqw.domain.performance.baseline-and-parity",
    "sqw.domain.plugin.package-registration-and-installed-proof", "sqw.domain.runtime.version-and-consistency",
    "sqw.domain.security.trust-boundary-and-negatives", "sqw.domain.source.external-authority",
    "sqw.review.tier-selection", "sqw.review.execution-and-requirements", "sqw.review.findings-and-result",
    "sqw.review.rubrics.accessibility", "sqw.review.rubrics.adversarial-decision", "sqw.review.rubrics.ml-ai",
    "sqw.review.rubrics.privacy-data-lifecycle", "sqw.review.rubrics.secret-handling",
    "sqw.review.rubrics.engineering-integrity", "sqw.review.rubrics.product-and-operability",
    "sqw.delegation.admission-and-contract", "sqw.delegation.fan-in-and-integration",
    "sqw.recovery.conflict-recovery", "sqw.recovery.repository-recovery", "sqw.recovery.cleanup",
    "sqw.runtime.stability-campaign", "sqw.workspace.artifact-and-fixture-ownership",
    "sqw.workspace.prototype-lifecycle", "sqw.recipes.dependency-lockfile-drift",
    "sqw.test.patterns.evaluation-fixture-curation", "sqw.test.patterns.implementation-parity",
    "sqw.test.patterns.dashboard-evidence", "sqw.test.patterns.contract-migration-proof",
    "sqw.test.patterns.optional-postprocess-boundary", "sqw.test.patterns.protocol-tool-stress",
    "sqw.test.patterns.public-adapter-migration-proof", "sqw.bridges.multi-source-synthesis",
    "sqw.bridges.source-target-gap-audit",
}
FACT_KEYS = {
    "schema_version", "route_phase", "request_mode", "intent_status", "root_cause_status", "implicated_surfaces",
    "unknown_implicated_facts", "surface_assessment", "persistence_need", "delegation_need",
    "external_side_effect", "pending_decision_ids", "available_artifact_ids", "completed_decision_ids",
    "just_completed_card_id", "decision_request",
}
RESULT_KEYS = {
    "schema_version", "route_action", "route_owner", "selected_decision_id", "primary_card",
    "required_artifact_ids", "reason_codes",
}
MAPPING_KEYS = {
    "decision_id", "card_id", "priority", "required_artifact_ids", "produced_artifact_ids",
    "positive_fixture_id", "near_miss_fixture_id",
}
class SoftwareDecisionProtocolV7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "decision-route-cases-v7.json").read_text(encoding="utf-8")
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
        facts_schema = self._load("schemas/route-facts.schema.json")
        result_schema = self._load("schemas/route-result.schema.json")
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
        manifest_schema = self._load("schemas/reference-cards-manifest.schema.json")
        Draft202012Validator.check_schema(manifest_schema)
        self.assertEqual([], list(Draft202012Validator(manifest_schema).iter_errors(manifest)))
        decision_map = self._load("registries/decision-card-map.json")
        cards = manifest["cards"]
        mappings = decision_map["decisions"]
        self.assertEqual("7.0.0", manifest["skill_version"])
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
            self.assertNotIn("neigh" + "bors", card)
            self.assertNotIn("max_active_" + "neigh" + "bors", card)
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

    def test_card_cycle_is_the_only_public_route_surface(self) -> None:
        self.assertTrue((SCRIPTS / "card_cycle.py").is_file())
        self.assertFalse((SCRIPTS / "resolve_reference_card.py").exists())
        policy = self._load("registries/policy-owners.json")
        owner = next(item for item in policy["policies"] if item["policy_id"] == "sqw.navigation.resolve")
        self.assertEqual("scripts/card_cycle.py", owner["owner_id"])

    def test_multi_step_sequence_and_precedence_are_deterministic(self) -> None:
        for sequence in self.fixture["sequence_cases"]:
            for step in sequence["steps"]:
                with self.subTest(sequence=sequence["id"], decision=step["expected_decision_id"]):
                    result = self._assess(step["facts"])
                    self.assertEqual("select_card", result["route_action"])
                    self.assertEqual(step["expected_decision_id"], result["selected_decision_id"])
                    self.assertEqual(step["expected_card_id"], result["primary_card"]["card_id"])
        recovery = self._assess(
            {"request_mode": "recovery", "pending_decision_ids": ["sqw.select.review.tier-selection"]}
        )
        self.assertEqual("sqw.select.entry.recovery", recovery["selected_decision_id"])
        plan = self._assess({"request_mode": "plan"})
        self.assertEqual(("handoff", "writing-plans"), (plan["route_action"], plan["route_owner"]))


if __name__ == "__main__":
    unittest.main()
