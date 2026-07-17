from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_offline_route_replay.py"
SPEC = importlib.util.spec_from_file_location("cross_skill_sequence_replay", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class CrossSkillRouteSequenceTests(unittest.TestCase):
    def test_report_executes_the_exact_active_inventory(self) -> None:
        report = replay.build_report()
        metrics = report["metrics"]
        self.assertEqual("offline-route-replay/2.0", report["schema_version"])
        self.assertEqual("deterministic_diagnostic", report["diagnostic_classification"])
        self.assertEqual((62, 62), (metrics["active_card_coverage_count"], metrics["active_card_count"]))
        self.assertEqual(1.0, metrics["entry_accuracy"])
        self.assertEqual(1.0, metrics["decision_precision"])
        self.assertEqual(1.0, metrics["decision_recall"])
        self.assertEqual(1.0, metrics["terminal_path_completion"])
        self.assertEqual(1.0, metrics["protected_negative_pass_rate"])
        self.assertEqual(0, metrics["unnecessary_card_loads"])
        self.assertLessEqual(metrics["per_step_active_bytes"]["maximum"], 8192)

    def test_both_skill_paths_reach_truthful_terminal_outcomes(self) -> None:
        report = replay.build_report()
        skills = {row["skill_id"] for row in report["sequence_rows"]}
        self.assertEqual({"writing-plans", "software-quality-workflows"}, skills)
        self.assertTrue(report["sequence_rows"])
        self.assertTrue(all(row["terminal_complete"] for row in report["sequence_rows"]))
        self.assertTrue(all(
            row["terminal_owner"] == ("software-quality-workflows" if row["skill_id"] == "writing-plans" else None)
            for row in report["sequence_rows"]
        ))
        self.assertTrue(all(report["gates"].values()))


if __name__ == "__main__":
    unittest.main()
