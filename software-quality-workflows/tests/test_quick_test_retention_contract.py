from __future__ import annotations

from pathlib import Path
import unittest


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class QuickTestRetentionContractTests(unittest.TestCase):
    def test_no_machine_retention_registry(self) -> None:
        skill_root = SKILL.parent
        machine_retention = [
            path for path in skill_root.rglob("*")
            if path.is_file()
            and "retention" in path.name.lower()
            and path.suffix in {".json", ".jsonl", ".yaml", ".yml"}
        ]
        self.assertEqual([], machine_retention)

    def test_retention_package_has_no_runtime_state(self) -> None:
        fixtures = SKILL.parent / "tests" / "fixtures"
        runtime_state = [
            path for name in ("workflow-events", "workflow-state")
            for path in (fixtures / name).rglob("*")
            if path.is_file()
        ]
        self.assertEqual([], runtime_state)


if __name__ == "__main__":
    unittest.main()
