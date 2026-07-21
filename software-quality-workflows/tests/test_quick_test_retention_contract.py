from __future__ import annotations

from pathlib import Path
import re
import unittest


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class QuickTestRetentionContractTests(unittest.TestCase):
    def test_retention_classes_and_current_diff_boundary(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        section = text.split("## Evidence and test retention", 1)[1].split("\n## ", 1)[0]
        identifiers = set(re.findall(r"`([a-z_]+)`", section))
        self.assertEqual({
            "durable_contract", "regression", "risk_boundary", "migration_temporary",
            "temporary_probe", "duplicate", "implementation_coupled",
        }, identifiers)
        self.assertIn("current diff", section)
        self.assertIn("Do not create a retention registry", section)

    def test_migration_temporary_has_a_deterministic_removal_contract(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        line = next(line for line in text.splitlines() if "`migration_temporary`" in line)
        for required in ("owner", "observable removal condition", "deterministic removal gate"):
            self.assertIn(required, line)


if __name__ == "__main__":
    unittest.main()
