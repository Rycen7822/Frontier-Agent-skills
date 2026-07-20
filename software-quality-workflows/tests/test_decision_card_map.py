from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from route_workflow import assess  # noqa: E402


class WorkflowRouteSequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision_map = self._load("registries/decision-card-map.json")
        self.selector_fixture = self._load("tests/fixtures/decision-route-cases-v8.json")
        self.sequence_fixture = self._load("tests/fixtures/workflow-route-sequences.json")

    @staticmethod
    def _load(relative: str) -> dict[str, object]:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise AssertionError(f"fixture must be an object: {relative}")
        return value

    def _assess(self, overlay: dict[str, object]) -> dict[str, object]:
        return assess({**self.selector_fixture["defaults"], **overlay})

    def test_sequence_fixture_consumes_the_single_decision_map(self) -> None:
        self.assertEqual("outcome-linked-route-sequences/1.0", self.sequence_fixture["schema_version"])
        self.assertEqual("software-quality-workflows", self.sequence_fixture["skill_id"])
        self.assertEqual(
            "tests/fixtures/decision-route-cases-v8.json",
            self.sequence_fixture["decision_case_fixture"],
        )
        mappings = self.decision_map["decisions"]
        positives = self.selector_fixture["positive_cases"]
        self.assertEqual(
            {(row["decision_id"], row["card_id"]) for row in mappings},
            {(case["decision_id"], case["expected_card_id"]) for case in positives},
        )

    def test_entry_routes_and_outcome_links_are_executable(self) -> None:
        entries = {case["id"]: case for case in self.sequence_fixture["entry_cases"]}
        mappings = {row["decision_id"]: row for row in self.decision_map["decisions"]}
        for case in entries.values():
            result = self._assess(case["facts"])
            expected = case["expected"]
            observed_card = result["primary_card"]["card_id"] if result["primary_card"] else None
            self.assertEqual(
                (expected["route_action"], expected["route_owner"], expected["selected_decision_id"], expected["card_id"]),
                (result["route_action"], result["route_owner"], result["selected_decision_id"], observed_card),
            )
        for sequence in self.sequence_fixture["workflow_sequences"]:
            completed: list[str] = []
            artifacts: list[str] = []
            previous = None
            for index, step in enumerate(sequence["steps"]):
                if index == 0:
                    facts = entries[sequence["entry_case_id"]]["facts"]
                else:
                    self.assertEqual(index - 1, step["requested_by_step"])
                    self.assertEqual(previous["produced_artifact_id"], step["request_artifact_id"])
                    facts = {
                        **self.selector_fixture["defaults"],
                        "completed_decision_ids": completed,
                        "available_artifact_ids": artifacts,
                        "just_completed_card_id": previous["card_id"],
                        "decision_request": {
                            "decision_id": step["decision_id"],
                            "produced_by_card_id": previous["card_id"],
                            "produced_artifact_id": step["request_artifact_id"],
                        },
                    }
                result = self._assess(facts)
                self.assertEqual((step["decision_id"], step["card_id"]), (
                    result["selected_decision_id"], result["primary_card"]["card_id"],
                ))
                self.assertIn(step["produced_artifact_id"], mappings[step["decision_id"]]["produced_artifact_ids"])
                completed.append(step["decision_id"])
                artifacts.append(step["produced_artifact_id"])
                previous = step
            terminal = sequence["terminal_outcome"]
            self.assertEqual("completed", terminal["status"])
            self.assertIsNone(terminal["owner"])
            self.assertEqual(terminal["required_decision_ids"], completed)
            self.assertEqual(terminal["required_artifact_ids"], artifacts)


if __name__ == "__main__":
    unittest.main()
