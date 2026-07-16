from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WritingDocsV4Tests(unittest.TestCase):
    def test_entry_version_structure_budget_and_router_boundary(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^  version: 4\.0\.0$")
        headings = [
            "## Owner boundary",
            "## Route",
            "## Profile selection",
            "## Closure boundary",
            "## One-card protocol",
            "## SQW handoff",
            "## Completion",
        ]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(sorted(positions), positions)
        self.assertEqual(headings, re.findall(r"(?m)^## .+$", text))
        self.assertLessEqual(len(text.encode("utf-8")), 6144)
        self.assertIn("zero or one `primary_card`", text)
        self.assertIn("reference-cards.manifest.json", text)
        self.assertIn("contract_frozen + plan_validated + handoff_emitted", text)
        self.assertIn("does not mean implementation, sign-off, publication, or workflow closure", text)
        self.assertNotIn("advance_closure.py", text)
        self.assertIn("Codex and Hermes Agent", text)
        self.assertIn("Resolve bundled paths from this skill root", text)
        audit = (ROOT / "references" / "design" / "evidence-and-decision-ledger.md").read_text(encoding="utf-8")
        self.assertNotIn("using Hermes tools", audit)

    def test_openai_metadata_is_narrow_and_exact(self) -> None:
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertEqual(
            "interface:\n"
            "  display_name: \"Writing Plans\"\n"
            "  short_description: \"Compile durable plans and closure contracts\"\n"
            "  default_prompt: \"Use $writing-plans to compile this software change into the lightest durable implementation plan and handoff.\"\n"
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            metadata,
        )
        self.assertIn('display_name: "Writing Plans"', metadata)
        self.assertIn('short_description: "Compile durable plans and closure contracts"', metadata)
        self.assertIn("$writing-plans", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)
        self.assertNotIn("execute", metadata.lower())

    def test_closure_contract_owners_are_split_from_runtime(self) -> None:
        model = "\n".join(
            (ROOT / "references" / "closure" / name).read_text(encoding="utf-8")
            for name in (
                "compile.md",
                "hard-constraints-and-corners.md",
                "assumptions-and-ambiguity.md",
                "search-and-publication-policy.md",
                "freeze-and-handoff.md",
            )
        )
        runtime = (ROOT / "operator" / "closure-contract-runtime.md").read_text(encoding="utf-8")
        for token in (
            "source precedence",
            "authority",
            "safe defaults",
            "hard constraint",
            "soft objectives",
            "corner",
            "verifier requirement",
            "search and publication",
            "SPEC_UNDERDETERMINED",
            "SPEC_UNSAT",
            "immutable",
            "plan-execution-handoff",
        ):
            self.assertIn(token.lower(), model.lower())
        self.assertIn("frozen contract independent of plan", model.lower())
        self.assertIn("not a model-facing reference card", runtime.lower())
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
            self.assertIn(status, runtime)

    def test_design_and_slicing_owners_preserve_decision_semantics(self) -> None:
        design = "\n".join(
            (ROOT / "references" / "design" / name).read_text(encoding="utf-8").lower()
            for name in (
                "depth-selection.md",
                "evidence-and-decision-ledger.md",
                "alternative-compression.md",
                "planning-gate.md",
            )
        )
        for token in (
            "d0",
            "d1",
            "d2",
            "owner/seam",
            "source identity",
            "counterevidence",
            "keep",
            "rewrite",
            "split",
            "merge",
            "defer",
            "delete",
            "replace",
            "false-green",
            "ready_for_slicing",
        ):
            self.assertIn(token, design)

        slicing = "\n".join(
            (ROOT / "references" / "slicing" / name).read_text(encoding="utf-8").lower()
            for name in ("outcome-slices.md", "context-capsules.md")
        )
        for token in (
            "vertical",
            "current frontier",
            "read/write/resource",
            "candidate",
            "mandatory",
            "on-demand",
            "sensitive",
            "truncation is always zero",
        ):
            self.assertIn(token, slicing)

    def test_profiles_economy_and_leaf_owners_preserve_source_contracts(self) -> None:
        required_tokens = {
            "profiles/brief.md": ("one observable outcome", "false-green", "create no graph/state/Closure Contract"),
            "profiles/handoff.md": ("ordered outcome slices", "current frontier", "standard execution"),
            "profiles/program.md": ("current frontier", "expand-migrate-contract", "8,192-byte"),
            "economy/output-classification.md": ("always-visible anchors", "warnings", "tiny budgets"),
            "economy/projection-and-verification.md": ("actual high-level agent envelope", "on-demand", "parity"),
            "decisions/architecture-decision-record.md": ("supersession", "publication authority", "alternatives"),
            "migration/deprecation-and-rollout.md": ("consumer oracle", "rollback window", "removal constraints"),
            "experiments/disposable-spike.md": ("admission", "freeze", "silent promotion"),
            "bridges/long-document-handoff.md": ("long-document segmented-writing", "source/coverage/evidence", "typed handoff blocker"),
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
