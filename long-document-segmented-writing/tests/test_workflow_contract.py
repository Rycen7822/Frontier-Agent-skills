from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_TEXT = (ROOT / "SKILL.md").read_text(encoding="utf-8")


class WorkflowContractTests(unittest.TestCase):
    def test_direct_gate_is_bounded_and_conjunctive(self) -> None:
        section = SKILL_TEXT.split("## Same-session Direct gate", 1)[1].split(
            "## Select one segmented profile", 1
        )[0]
        for boundary in ("at most 4 source files", "at most 32 KiB", "at most 6 sections", "at most 8 KiB"):
            self.assertIn(boundary, section)
        self.assertIn("only when all of these facts are true", section)

    def test_direct_gate_forbids_recovery_artifact_proliferation(self) -> None:
        section = SKILL_TEXT.split("## Same-session Direct gate", 1)[1].split(
            "## Select one segmented profile", 1
        )[0]
        for artifact in (
            "scratch root", "owner allocation", "ledger", "section drafts",
            "confidence review", "`CODEX_STATE.md`", "receipt", "worknote", "sidecar",
        ):
            self.assertIn(artifact, section)
        self.assertIn("do not inspect `agents/openai.yaml`", section)
        self.assertIn("do not run assembler section/output modes", section)

    def test_compact_has_one_ledger_and_at_most_four_draft_shards(self) -> None:
        compact_row = next(
            line for line in SKILL_TEXT.splitlines() if line.startswith("| compact |")
        )
        self.assertIn("One `scratch-ledger.md`", compact_row)
        self.assertIn("1–4 ordered draft shards", compact_row)
        self.assertIn("confidence gaps stay in the ledger", compact_row)
        self.assertNotIn("confidence-review.md", compact_row)

    def test_full_thresholds_and_single_confidence_owner_remain(self) -> None:
        full_row = next(
            line for line in SKILL_TEXT.splitlines() if line.startswith("| full |")
        )
        for threshold in ("sources exceed 12", "final sections exceed 10", "ledger would exceed 16 KiB"):
            self.assertIn(threshold, full_row)
        self.assertEqual(1, len(re.findall(r"one confidence review", full_row, flags=re.IGNORECASE)))


if __name__ == "__main__":
    unittest.main()
