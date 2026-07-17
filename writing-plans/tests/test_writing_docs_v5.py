from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WritingDocsV5Tests(unittest.TestCase):
    def test_entry_version_structure_budget_and_router_boundary(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  version: 5\.0\.0$")
        headings = [
            "## Owner boundary", "## Route", "## Profile selection", "## One-card protocol",
            "## SQW handoff", "## Completion",
        ]
        self.assertEqual(headings, re.findall(r"(?m)^## .+$", text))
        self.assertLessEqual(len(text.encode("utf-8")), 6144)
        for anchor in (
            "zero or one `primary_card`", "registries/decision-card-map.json", "just-completed mapped card",
            "references/package-support-map.md", "Codex and Hermes Agent",
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
            "  allow_implicit_invocation: false\n",
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
            "bridges/long-document-handoff.md": ("long-document segmented-writing", "source/coverage/evidence"),
            "slicing/outcome-slices.md": ("topologically ready current frontier", "schema-valid decision request"),
            "slicing/context-capsules.md": ("mandatory truncation is always zero", "on-demand"),
        }
        for relative, anchors in required.items():
            text = (ROOT / "references" / relative).read_text(encoding="utf-8").lower()
            for anchor in anchors:
                with self.subTest(card=relative, anchor=anchor):
                    self.assertIn(anchor.lower(), text)

    def test_templates_match_state_2_contract(self) -> None:
        brief = (ROOT / "templates" / "brief-change-card.md").read_text(encoding="utf-8")
        handoff = (ROOT / "templates" / "executable-handoff.md").read_text(encoding="utf-8")
        program = (ROOT / "templates" / "program-migration-map.md").read_text(encoding="utf-8")
        self.assertIn("Completion:", brief)
        self.assertIn("Requirement anchors", handoff)
        self.assertIn("## Strategy families", program)
        self.assertIn("## Verification and completion", program)


if __name__ == "__main__":
    unittest.main()
