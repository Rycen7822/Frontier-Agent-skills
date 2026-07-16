from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_offline_route_replay.py"
SPEC = importlib.util.spec_from_file_location("evaluate_offline_route_replay", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class OfflineRouteReplayTests(unittest.TestCase):
    def test_checked_report_is_reproducible_strict_and_deterministic_only(self) -> None:
        generated = replay.build_report()
        checked = json.loads((ROOT / "evaluation" / "offline-route-replay.json").read_text(encoding="utf-8"))
        self.assertEqual(generated, checked)
        schema = json.loads(
            (ROOT / "evaluation" / "schemas" / "offline-route-replay.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(checked)))
        self.assertEqual("deterministic_route_ready", checked["decision"])
        self.assertTrue(all(checked["gates"].values()))
        self.assertIsNone(checked["metrics"]["hidden_primary_card_accuracy"])
        self.assertIn("natural model routing and outcome quality require real Sol max runs", checked["limitations"])

    def test_replay_binds_the_exact_atomic_version_pair(self) -> None:
        report = json.loads((ROOT / "evaluation" / "offline-route-replay.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {"software-quality-workflows": "4.0.0", "writing-plans": "3.0.0"},
            report["baseline"]["skill_versions"],
        )
        self.assertEqual(
            {"software-quality-workflows": "5.0.0", "writing-plans": "4.0.0"},
            report["vnext"]["skill_versions"],
        )
        self.assertEqual(len(report["rows"]), len({row["pair_id"] for row in report["rows"]}))
        self.assertTrue(all(row["vnext_active_cards"] <= 1 for row in report["rows"]))


if __name__ == "__main__":
    unittest.main()
