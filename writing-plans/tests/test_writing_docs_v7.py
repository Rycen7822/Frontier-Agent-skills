from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WritingDocsV7Tests(unittest.TestCase):
    def test_entry_version_structure_budget_and_router_boundary(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  version: 7\.0\.0$")
        headings = [
            "## Owner boundary", "## Card-cycle entry", "## Selection and profiles", "## One-card context",
            "## Program anchor lifecycle", "## Completion",
        ]
        self.assertEqual(headings, re.findall(r"(?m)^## .+$", text))
        self.assertLessEqual(len(text.encode("utf-8")), 5200)
        for anchor in (
            "LC_ALL=C scripts/card_cycle.py route --help", "previous stdout unchanged", "one projection/boundary",
            "terminal-disposable", "Codex and Hermes Agent", "migration_or_rollback=true` only if",
            "resume_required=true` only for", "same_session_execution=true` when",
            "schema-valid `field_examples`", "Pass completion stdout unchanged",
        ):
            self.assertIn(anchor, text)

    def test_openai_metadata_is_narrow_and_exact(self) -> None:
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertEqual(
            "interface:\n"
            "  display_name: \"Writing Plans\"\n"
            "  short_description: \"Compile durable software plans and handoffs\"\n"
            "  default_prompt: \"Use $writing-plans to compile this software change into the lightest durable implementation plan and handoff.\"\n"
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            metadata,
        )
        self.assertNotIn("execute", metadata.lower())

    def test_design_card_preserves_depth_evidence_alternatives_and_gate(self) -> None:
        text = (ROOT / "references" / "design" / "decision-resolution.md").read_text(encoding="utf-8").lower()
        for anchor in (
            "d0", "d1", "d2", "owner/seam", "counterevidence", "false-green", "ready_for_slicing",
            "keep", "rewrite", "split", "merge", "defer", "delete", "replace",
        ):
            self.assertIn(anchor, text)

    def test_consolidated_cards_preserve_unique_operational_obligations(self) -> None:
        required = {
            "profiles/program.md": ("supersession lineage", "publication authority", "expand-migrate-contract"),
            "economy/output-projection.md": ("always-visible anchor", "tiny budgets", "parity"),
            "migration/deprecation-and-rollout.md": ("consumer oracle", "rollback/removal constraints"),
            "experiments/disposable-spike.md": ("silent promotion", "falsification criterion"),
            "bridges/long-document-handoff.md": ("long-document segmented-writing", "scratch_retention", "final locator/hash"),
            "slicing/outcome-slices.md": ("topologically ready current frontier", "schema-valid decision request"),
            "slicing/context-capsules.md": ("mandatory truncation is always zero", "on-demand"),
        }
        for relative, anchors in required.items():
            text = (ROOT / "references" / relative).read_text(encoding="utf-8").lower()
            for anchor in anchors:
                with self.subTest(card=relative, anchor=anchor):
                    self.assertIn(anchor.lower(), text)

    def test_templates_match_typed_state_3_contract(self) -> None:
        brief = (ROOT / "templates" / "brief-change-card.md").read_text(encoding="utf-8")
        handoff = (ROOT / "templates" / "executable-handoff.md").read_text(encoding="utf-8")
        program = (ROOT / "templates" / "program-migration-map.md").read_text(encoding="utf-8")
        self.assertIn("Completion:", brief)
        self.assertIn("Typed Executable Handoff v3", handoff)
        self.assertIn("does not grant or claim actual authority", handoff)
        self.assertNotIn("state path", handoff.lower().replace("no filesystem state path", ""))
        self.assertIn("State binding:", program)
        self.assertIn("disposable projection", program)
        self.assertNotIn("State ref:", program)


if __name__ == "__main__":
    unittest.main()
