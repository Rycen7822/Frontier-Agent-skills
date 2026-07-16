from __future__ import annotations

import json
import os
import unittest
from pathlib import Path


SQW_ROOT = Path(__file__).resolve().parents[1]
WRITING_ROOT = SQW_ROOT.parent / "writing-plans"
_LONG_DOCUMENT_ENV = os.environ.get("LONG_DOCUMENT_SKILL_ROOT")
LONG_DOCUMENT_ROOT = Path(_LONG_DOCUMENT_ENV).expanduser().resolve() if _LONG_DOCUMENT_ENV else None


class VNextP0ContractTests(unittest.TestCase):
    def test_phase0_route_fixtures_are_frozen(self) -> None:
        workflow = json.loads(
            (SQW_ROOT / "tests" / "fixtures" / "workflow-route-cases.json").read_text(
                encoding="utf-8"
            )
        )
        plans = json.loads(
            (WRITING_ROOT / "tests" / "fixtures" / "plan-route-cases.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("2.0", workflow["schema_version"])
        self.assertEqual("2.0", plans["schema_version"])
        self.assertGreaterEqual(len(workflow["cases"]), 16)
        self.assertGreaterEqual(len(plans["cases"]), 12)
        for payload in (workflow, plans):
            ids = [case["id"] for case in payload["cases"]]
            self.assertEqual(len(ids), len(set(ids)))
            for case in payload["cases"]:
                self.assertIsInstance(case["facts"], dict)
                self.assertIn("expected", case)

    def test_vnext_entry_contract(self) -> None:
        sqw = (SQW_ROOT / "SKILL.md").read_text(encoding="utf-8")
        writing = (WRITING_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Default umbrella for all software development work", sqw)
        self.assertNotIn("All software development tasks enter through this skill", sqw)
        self.assertNotIn("**Always use before:**", writing)
        self.assertIn("version: 5.0.0", sqw)
        self.assertIn("version: 4.0.0", writing)
        self.assertIn("M0 Direct", sqw)
        for profile in ("Brief (`wp.profiles.brief`)", "Handoff (`wp.profiles.handoff`)", "Program (`wp.profiles.program`)"):
            self.assertIn(profile, writing)

    def test_scoped_closure_vocabulary(self) -> None:
        writing = (WRITING_ROOT / "SKILL.md").read_text(encoding="utf-8")
        sqw = (SQW_ROOT / "SKILL.md").read_text(encoding="utf-8")
        texts = [writing, sqw]
        if LONG_DOCUMENT_ROOT is not None:
            texts.append((LONG_DOCUMENT_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        for text in texts:
            self.assertNotIn("100% confidence", text)
            self.assertNotIn("100% 自信", text)
        for status in (
            "needs_repair",
            "verified_within_scope",
            "blocked",
            "empirical_validation_required",
        ):
            self.assertIn(status, sqw)
        self.assertIn("unproven", writing)

    def test_route_profiles_and_modes_cover_counterexamples(self) -> None:
        workflow = json.loads(
            (SQW_ROOT / "tests" / "fixtures" / "workflow-route-cases.json").read_text(encoding="utf-8")
        )
        plans = json.loads(
            (WRITING_ROOT / "tests" / "fixtures" / "plan-route-cases.json").read_text(encoding="utf-8")
        )
        workflow_cases = {case["id"]: case["expected"] for case in workflow["cases"]}
        plan_cases = {case["id"]: case["expected"] for case in plans["cases"]}
        required_workflow_cases = {
            "known_public_contract_surface",
            "trace_only_change",
            "durable_change",
            "eligible_admission_enters_wp_compile",
            "terminal_admission_emits_terminal",
        }
        self.assertTrue(required_workflow_cases.issubset(workflow_cases))
        self.assertEqual(
            {None, "M0_DIRECT", "M1_TRACE", "M2_SPARSE"},
            {case.get("workflow_mode") for case in workflow_cases.values()},
        )
        self.assertEqual("M0_DIRECT", workflow_cases["routine_local_change"]["workflow_mode"])
        self.assertEqual("systematic-debugging", workflow_cases["unknown_failure"]["primary_owner_id"])
        self.assertEqual("M2_SPARSE", workflow_cases["durable_change"]["workflow_mode"])
        self.assertEqual("brief", plan_cases["explicit_brief"]["profile"])
        self.assertEqual("program", plan_cases["public_resume_program"]["profile"])
        self.assertEqual("long-document", plan_cases["long_corpus_handoff"]["route"])

    def test_reference_budget_review_tiers_and_conditional_authority(self) -> None:
        sqw = (SQW_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(sqw.encode("utf-8")), 7_168)
        self.assertLessEqual(len((WRITING_ROOT / "SKILL.md").read_bytes()), 6_144)
        for mode in ("M0 Direct", "M1 Trace", "M2 Sparse", "M3 Full"):
            self.assertIn(mode, sqw)
        for tier in ("R0", "R1", "R2"):
            self.assertIn(tier, sqw)
        self.assertIn("zero or one exact `primary_card`", sqw)
        self.assertIn("at most three exact cards", sqw)
        self.assertNotIn("references/authority-and-scope.md", sqw)
        safety = SQW_ROOT / "references" / "safety"
        self.assertIn("M0", (safety / "scope-and-dirty-worktree.md").read_text(encoding="utf-8"))
        self.assertIn("READ_ONLY", (safety / "side-effect-risk.md").read_text(encoding="utf-8"))
        self.assertIn("scan_candidate", (safety / "evidence-coverage-and-freshness.md").read_text(encoding="utf-8"))
        delegated = (SQW_ROOT / "references" / "delegation" / "admission-and-slicing.md").read_text(encoding="utf-8")
        self.assertIn("M2/M3 execution", delegated)
        self.assertIn("overlapping writes/resources", delegated)

    def test_new_major_removes_compatibility_paths(self) -> None:
        writing = (WRITING_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("git commit", writing.lower())
        self.assertNotIn("python -m pytest", writing.lower())
        self.assertIn("SQW independently owns execution and proof", writing)
        names = {path.name for path in (WRITING_ROOT / "references").glob("*.md")}
        compatibility_paths = {
            "context-compaction-resistant-upgrade-plans.md",
            "evidence-backed-standalone-roadmaps.md",
            "research-reference-materials.md",
            "fillable-requirements-glossary-pattern.md",
            "local-artifact-cleanup-and-benchmark-fixture-expansion.md",
            "legacy-manifest-diff-compatibility.md",
            "result-preserving-optimization-plans.md",
            "plan-absorbed-skill.md",
            "spike-absorbed-skill.md",
        }
        self.assertTrue(compatibility_paths.isdisjoint(names))
        for name in compatibility_paths:
            self.assertFalse((WRITING_ROOT / "references" / name).exists(), name)
        owner_expectations = {
            "entry/intent-discovery.md": "# Intent Discovery",
            "workspace/task-artifact-ownership.md": "# Task-Artifact Ownership",
            "test/patterns/benchmark-fixture-curation.md": "# Benchmark Fixture Curation Pattern",
            "test/patterns/legacy-manifest-comparison.md": "# Legacy Manifest Comparison Pattern",
            "domain/performance/optimization-and-parity.md": "# Performance Optimization and Parity",
        }
        for key, marker in owner_expectations.items():
            filename = key.split("#", 1)[0]
            text = (SQW_ROOT / "references" / filename).read_text(encoding="utf-8")
            self.assertIn(marker, text)

    def test_long_document_owner_does_not_reclaim_software_policy(self) -> None:
        if LONG_DOCUMENT_ROOT is None:
            self.skipTest("LONG_DOCUMENT_SKILL_ROOT is not set")
        text = (LONG_DOCUMENT_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Brief Change Card", text)
        self.assertNotIn("M2 Sparse", text)
        self.assertIn("source inventory", text.lower())
        self.assertIn("whole-draft", text.lower())


if __name__ == "__main__":
    unittest.main()
