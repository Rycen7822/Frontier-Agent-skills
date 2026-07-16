from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _workflow_state import load_json  # noqa: E402
from assess_closure_admission import assess_admission  # noqa: E402
from local_workflow_adapter import AdapterConflict  # noqa: E402
from test_closure_admission import BASE as ADMISSION_BASE  # noqa: E402
from test_candidate_task_records import _search_adapter  # noqa: E402
from test_closure_worktree_adapter import _git, _repository  # noqa: E402


SCENARIOS = ROOT / "tests" / "fixtures" / "closure" / "repository-safety-scenarios.json"
TRAJECTORIES = ROOT / "tests" / "fixtures" / "closure" / "controller-trajectories.json"


class RepositorySafetyScenarioTests(unittest.TestCase):
    def test_exact_eight_local_repositories_cover_required_scenarios_and_terminal_contracts(self) -> None:
        fixture = load_json(SCENARIOS)
        scenarios = fixture["scenarios"]
        self.assertEqual(8, len(scenarios))
        self.assertEqual(8, len({item["id"] for item in scenarios}))
        self.assertFalse(fixture["remote_writes"])
        self.assertFalse(fixture["multi_candidate_enabled"])
        required = {
            "deterministic bugfix", "API migration with compatibility test", "flaky test diagnosis",
            "performance task with parity gate", "security boundary task", "underdetermined product request",
            "verifier hacking trap", "source drift/concurrent edit",
        }
        self.assertEqual(required, {item["class"] for item in scenarios})
        trajectories = {item["id"]: item["expected_terminal"] for item in load_json(TRAJECTORIES)["closure"]}

        with tempfile.TemporaryDirectory() as directory:
            for index, scenario in enumerate(scenarios, 1):
                with self.subTest(scenario=scenario["id"]):
                    scenario_root = Path(directory) / scenario["id"]
                    scenario_root.mkdir()
                    repo, revision = _repository(scenario_root)
                    self.assertFalse(_git(repo, "remote"), "safety-scenario repo must have no remote")
                    adapter = _search_adapter(repo, revision)
                    candidate_id = f"CAND-{index:04d}"
                    action = scenario["action"]
                    if scenario["trajectory"] == "preworkflow-admission":
                        self.assertEqual("no_candidate", action)
                        admission = assess_admission({**ADMISSION_BASE, **scenario["admission_overrides"]})
                        self.assertEqual("TERMINAL", admission["decision"])
                        self.assertEqual(scenario["expected_terminal"], admission["terminal_status"])
                        self.assertNotIn(scenario["trajectory"], trajectories)
                        continue
                    if action == "no_candidate":
                        self.assertFalse((adapter.root / "worktrees").exists())
                        self.assertIn(scenario["trajectory"], trajectories)
                        self.assertEqual(scenario["expected_terminal"], trajectories[scenario["trajectory"]])
                        continue
                    created = adapter.create_candidate_worktree(
                        repo, candidate_id=candidate_id, base_revision=revision, writer_id="worker-01",
                        allowed_write_paths=["src/payments/**", "tests/payments/**"],
                        protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
                    )
                    worktree = Path(created["worktree_path"])
                    if action in {"allowed_edit", "allowed_edit_with_test"}:
                        (worktree / "src" / "payments" / "charge.py").write_text(
                            f"def charge():\n    return '{scenario['id']}'\n", encoding="utf-8"
                        )
                        if action == "allowed_edit_with_test":
                            (worktree / "tests" / "payments" / "compat.py").write_text("COMPATIBLE = True\n", encoding="utf-8")
                        snapshot = adapter.inspect_candidate_snapshot(
                            repo, candidate_id=candidate_id, expected_base_revision=revision,
                            allowed_write_paths=["src/payments/**", "tests/payments/**"],
                            protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
                        )
                        self.assertTrue(snapshot["eligible_for_archive"])
                        self.assertEqual([], snapshot["protected_surface_changes"])
                    elif action == "protected_edit":
                        (worktree / "tests" / "holdout" / "secret_case.py").write_text("HIDDEN = False\n", encoding="utf-8")
                        snapshot = adapter.inspect_candidate_snapshot(
                            repo, candidate_id=candidate_id, expected_base_revision=revision,
                            allowed_write_paths=["src/payments/**", "tests/payments/**"],
                            protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
                        )
                        self.assertFalse(snapshot["eligible_for_archive"])
                        self.assertEqual(["tests/holdout/secret_case.py"], snapshot["protected_surface_changes"])
                    elif action == "source_drift":
                        (repo / "src" / "payments" / "charge.py").write_text("def charge():\n    return 'concurrent'\n", encoding="utf-8")
                        _git(repo, "add", "src/payments/charge.py")
                        _git(repo, "commit", "-qm", "concurrent source change")
                        with self.assertRaisesRegex(AdapterConflict, "E_SOURCE_DRIFT"):
                            adapter.inspect_candidate_snapshot(
                                repo, candidate_id=candidate_id, expected_base_revision=revision,
                                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                                protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
                            )
                    self.assertIn(scenario["trajectory"], trajectories)
                    self.assertEqual(scenario["expected_terminal"], trajectories[scenario["trajectory"]])


if __name__ == "__main__":
    unittest.main()
