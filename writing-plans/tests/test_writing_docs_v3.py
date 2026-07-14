from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WritingDocsV3Tests(unittest.TestCase):
    def test_entry_version_structure_budget_and_exact_reference_map(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^version: 3\.0\.0$")
        headings = [
            "## Owner contract",
            "## Route before planning",
            "## Autonomous closure branch",
            "## Select Brief / Handoff / Program",
            "## Compile and freeze contract",
            "## Build the canonical plan",
            "## Progressive disclosure",
            "## Handoff to SQW",
            "## Completion",
            "## Reference map",
        ]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(sorted(positions), positions)
        self.assertLess(len(text.encode("utf-8")), 16000)
        reference_section = text[text.index("## Reference map") :]
        links = set(re.findall(r"\]\((references/[^)]+)\)", reference_section))
        self.assertEqual(
            {
                "references/architecture-decision-records.md",
                "references/closure-contract.md",
                "references/context-and-output-economy-plans.md",
                "references/deprecation-migration-plans.md",
                "references/design-audit-compression-ledger.md",
                "references/implementation-slicing-and-context-capsules.md",
                "references/plan-profiles.md",
                "references/plan-state-contract.md",
                "references/spike.md",
            },
            links,
        )
        for link in links:
            self.assertTrue((ROOT / link).is_file(), link)
        self.assertIn("contract_frozen + plan_validated + handoff_emitted", text)
        self.assertIn("does not mean implementation, sign-off, publication, or workflow closure", text)
        self.assertNotIn("advance_closure.py", text)

    def test_openai_metadata_is_narrow_and_exact(self) -> None:
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertEqual(
            "interface:\n"
            "  display_name: Writing Plans\n"
            "  short_description: Compile a durable implementation plan or frozen closure contract\n"
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            metadata,
        )
        self.assertIn("display_name: Writing Plans", metadata)
        self.assertIn("short_description: Compile a durable implementation plan or frozen closure contract", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)
        self.assertNotIn("execute", metadata.lower())

    def test_closure_contract_reference_has_fixed_owner_sections(self) -> None:
        text = (ROOT / "references" / "closure-contract.md").read_text(encoding="utf-8")
        headings = re.findall(r"(?m)^## .+$", text)
        self.assertEqual(
            [
                "## Ownership and activation",
                "## Source hierarchy and intent inference",
                "## Authority and autonomy ceiling",
                "## Assumptions and safe defaults",
                "## Hard constraints",
                "## Soft objectives and lexicographic order",
                "## Corner selection",
                "## Verifier requirements",
                "## Search and publication policy",
                "## Ambiguity / unsat certificates",
                "## Freeze, epoch, supersession",
                "## Handoff to SQW",
                "## Completion criterion",
            ],
            headings,
        )
        for pointer in ("design-audit-compression-ledger.md", "spike.md", "deprecation-migration-plans.md", "plan-state-contract.md", "authority-and-scope.md", "intent-and-design-discovery.md", "verifier-kernel.md", "autonomous-closure.md"):
            self.assertIn(pointer, text)
        self.assertIn("must not contain a plan reference", text)
        self.assertIn("SPEC_UNDERDETERMINED", text)
        for status in (
            "CLOSED",
            "SPEC_UNDERDETERMINED",
            "SPEC_UNSAT",
            "AUTHORITY_BLOCKED",
            "ENVIRONMENT_UNAVAILABLE",
            "BASELINE_UNSTABLE",
            "VERIFIER_UNQUALIFIED",
            "NON_CONVERGED",
            "BUDGET_EXHAUSTED",
            "WORKFLOW_INVALID",
            "ABORTED_BY_SOURCE_DRIFT",
        ):
            self.assertIn(status, text)

    def test_retained_references_are_synchronized_to_v3_contract(self) -> None:
        required_tokens = {
            "plan-profiles.md": ("Execution policy", "Constraint coverage", "Brief", "Handoff"),
            "plan-state-contract.md": ("1.1", "closure_contract_ref", "dual ledger", "candidate"),
            "context-and-output-economy-plans.md": ("contract hash", "incumbent", "hard failures", "budget"),
            "implementation-slicing-and-context-capsules.md": ("closure phase", "candidate", "canonical plan node"),
            "design-audit-compression-ledger.md": ("strategy family", "epoch", "noninteractive", "certificate"),
            "architecture-decision-records.md": ("sign-off-ready", "incumbent"),
            "deprecation-migration-plans.md": ("consumer oracle", "rollback window", "removal constraint"),
            "spike.md": ("admission", "freeze", "silent promotion"),
        }
        for name, tokens in required_tokens.items():
            text = (ROOT / "references" / name).read_text(encoding="utf-8").lower()
            for token in tokens:
                with self.subTest(reference=name, token=token):
                    self.assertIn(token.lower(), text)

    def test_templates_keep_closure_out_of_brief_and_bind_program(self) -> None:
        brief = (ROOT / "templates" / "brief-change-card.md").read_text(encoding="utf-8")
        handoff = (ROOT / "templates" / "executable-handoff.md").read_text(encoding="utf-8")
        program = (ROOT / "templates" / "program-migration-map.md").read_text(encoding="utf-8")
        self.assertNotIn("Closure contract", brief)
        self.assertIn("Execution policy: standard", handoff)
        self.assertIn("Requirement anchors", handoff)
        self.assertIn("## Constraint coverage", program)
        self.assertIn("## Strategy families", program)


if __name__ == "__main__":
    unittest.main()
