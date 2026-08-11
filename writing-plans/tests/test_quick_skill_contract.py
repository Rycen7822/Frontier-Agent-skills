from __future__ import annotations

from pathlib import Path
import re
import unittest

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = SKILL_ROOT / "SKILL.md"
HANDOFF_FIELDS = {
    "Goal / non-goals",
    "Bound source identity",
    "Protected work and allowed effects",
    "Settled decisions",
    "First source-changing slice and files/symbols",
    "Acceptance and verification",
    "Rollback/cleanup when material",
    "Later blockers and dependencies",
    "freshness-bound host attestation",
    "Exact next source-changing action",
}
PROGRAM_FIELDS = {
    "Milestones in dependency order, each with acceptance",
    "Current frontier",
    "Migration/deprecation owner and removal condition when applicable",
    "Update-in-place rule",
}


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not match:
        raise AssertionError("missing YAML frontmatter")
    value = yaml.safe_load(match.group(1))
    if not isinstance(value, dict):
        raise AssertionError("invalid YAML frontmatter")
    return value


class QuickWritingPlansTests(unittest.TestCase):
    def test_metadata_budget_and_implicit_activation(self) -> None:
        metadata = frontmatter(SKILL_PATH)
        self.assertEqual("8.3.0", metadata["metadata"]["version"])
        self.assertEqual(
            "Write source-bound software implementation Handoffs and "
            "multi-session Programs from settled decisions; not diagnosis "
            "or execution.",
            metadata["description"],
        )
        description = metadata["description"].casefold()
        self.assertGreaterEqual(len(description), 80)
        for term in ("source-bound", "software implementation", "handoff", "program"):
            self.assertIn(term, description)
        self.assertLessEqual(len(SKILL_PATH.read_bytes()), 6400)
        agents = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(agents["policy"]["allow_implicit_invocation"], True)

    def test_package_has_single_runtime_body(self) -> None:
        self.assertEqual([SKILL_PATH], sorted(SKILL_ROOT.rglob("*.md")))

    def test_no_reference_template_script_schema_or_operator_tree(self) -> None:
        for name in ("references", "templates", "scripts", "schemas", "operator"):
            self.assertFalse((SKILL_ROOT / name).exists())

    def test_handoff_and_program_contracts_are_inline(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8")
        for field in HANDOFF_FIELDS | PROGRAM_FIELDS:
            self.assertIn(field, body)
        rows = ("- State —", "- Resume —", "- Slice —", "- Proof —")
        self.assertEqual(list(rows), sorted(rows, key=body.index))
        self.assertIn("directly from settled facts", body)
        self.assertIn(
            "Acceptance and verification: the one combined final proof command",
            body,
        )

    def test_rows_have_exclusive_ownership_without_fact_loss(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8")
        row_markers = {
            "- State —": (
                "Bound source identity",
                "Protected work and allowed effects",
                "Settled decisions",
                "Exact first-slice inputs, outputs, values, invariants",
                "Later blockers and dependencies",
            ),
            "- Resume —": ("freshness-bound host attestation",),
            "- Slice —": (
                "Goal / non-goals",
                "First source-changing slice and files/symbols",
                "Exact next source-changing action",
            ),
            "- Proof —": (
                "Acceptance and verification",
                "Rollback/cleanup when material",
            ),
        }
        for row, markers in row_markers.items():
            line = next(line for line in body.splitlines() if line.startswith(row))
            for marker in markers:
                with self.subTest(row=row, marker=marker):
                    self.assertIn(marker, line)
                    self.assertEqual(1, body.count(marker))

    def test_transfer_consumes_matching_preflight(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in (
            "consume a matching freshness-bound host attestation",
            "resolved root, bound source identity, freshness, and dirty scope match",
            "transfer it unchanged",
            "missing or mismatched",
            "one combined preflight",
            "do not rerun it",
        ):
            self.assertIn(contract, body)
        self.assertNotIn("root/revision/head/dirty scope", body)

    def test_program_edits_preserve_observed_transformations_and_name_dependencies(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in (
            "dependencies name every prerequisite milestone",
            "never ordinals or collective references",
            "executable against the observed body",
            "carry every preserved transformation/invariant into code, not prose",
            "explicit edit missing a promised preserved transformation/invariant",
        ):
            self.assertIn(contract, body)

    def test_verification_owner_is_observed_not_inferred(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in (
            "prompt-bound verification command",
            "do not block the plan or invent a full-suite command",
            "repository's test owner supplies any broader proof",
        ):
            self.assertIn(contract, body)

    def test_protected_behavior_is_bound_once(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        self.assertIn("observed protected-test i/o and values", body)
        self.assertIn("later slice and proof rows reference state", body)
        self.assertEqual(1, body.count("observed protected-test i/o and values"))

    def test_proof_is_the_only_post_edit_command(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in (
            "only post-edit command",
            "behavior, diff scope, protected boundary, residue, and whitespace",
            "after proof, run no status, diff, test, or confirmation",
            "planner-only non-content confirmation",
            "never put it in the executor plan",
        ):
            self.assertIn(contract, body)

    def test_source_binding_and_first_source_change_are_distinct(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8")
        self.assertLess(
            body.index("revision or explicit non-Git identity"),
            body.index("freshness-bound host attestation"),
        )
        self.assertLess(
            body.index("freshness-bound host attestation"),
            body.index("Exact next source-changing action"),
        )

    def test_native_plan_binds_available_source_once(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in (
            "inspect each available bound file once",
            "observed symbols and behavior",
            "exact edits, checks, expected results, and failure exits",
            "complete runnable test bodies when exact tests are requested",
            "include `pythonpath` when needed",
            '"follow existing conventions"',
            "must end as a native ordered plan",
            "even when git identity, dirty/protected paths, or exact source identity are visible",
            "a native proof never adds whole-file snapshots",
            "argument-parser calls",
            "make the residual check identifier-aware",
            "same collected identifier set",
            "tokenizer token-type constant",
            "non-git identity forbids git status, diff, or rollback",
        ):
            self.assertIn(contract, body)

    def test_test_command_has_one_cwd_and_disables_pytest_cache(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        self.assertIn("derive one starting cwd and module path", body)
        self.assertIn("never `cd` into the stated cwd again", body)
        self.assertIn("python -m pytest -p no:cacheprovider", body)

    def test_one_canonical_deliverable_and_no_sidecars(self) -> None:
        files = {
            path.relative_to(SKILL_ROOT).as_posix()
            for path in SKILL_ROOT.rglob("*")
            if path.is_file()
        }
        self.assertEqual({
            "SKILL.md",
            "agents/openai.yaml",
            "tests/test_quick_skill_contract.py",
        }, files)

    def test_postwrite_checks_do_not_reemit_the_plan(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in ("before return", "do not reopen", "git diff --check"):
            self.assertIn(contract, body)
        self.assertIn("never calculate a plan/document hash", body)
        self.assertNotIn("status/hash", body)

    def test_minimal_sufficient_plan_and_execution_contract(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in (
            "minimal sufficient form",
            "repo-relative dirty/protected and first-slice paths",
            "assigning each fact to one row",
            "one combined preflight",
            "one combined final proof command",
            "at most one combined planner-only non-content confirmation",
            "do not expand one sentence into its own heading",
            "skill-source changes use skill authoring",
            "portable identity",
            "no word/byte reduction target",
            "each prose paragraph on one physical line",
            "line breaks only at markdown structural boundaries",
            "never inside a sentence or merely to fit a column",
            "one contract table or a three- or four-row bullet contract",
            "exact first-slice inputs, outputs, values, invariants",
            "fill rows directly from settled facts",
            "state behavior, not just a symbol/test",
            "program uses those rows",
            "exclude the named plan deliverable itself",
            "never compare against the original absolute root",
            "globally clean status",
            "use invocation-bound source; do not reread it",
            "treat named plan/owner/test/symbol paths as resolved",
            "do not inventory, seek alternate owners, or check existence",
            "only a later planning invocation updates the program",
            "protected immutable input",
            "dependencies name every prerequisite milestone, never ordinals",
            "required resume without attestation acceptance or one-preflight fallback",
            "do not instruct execution to modify the plan",
            "repository's test owner",
            "state the narrow checks implied by those bindings",
            "prefix tests with `pythondontwritebytecode=1`",
            "python -m unittest <repo-test>",
            "python -m pytest -p no:cacheprovider",
            "exact cleanup",
        ):
            self.assertIn(contract, body)
        self.assertIn("state contains current frontier and later blockers", body)
        self.assertIn("slice contains named milestones in dependency order", body)

    def test_no_host_injection_reread_workaround(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for workaround in (
            "complete body in the invocation",
            "metadata/path only",
            "host-injected",
            "host injected",
        ):
            self.assertNotIn(workaround, body)

    def test_no_brief_surface(self) -> None:
        self.assertNotIn("brief", SKILL_PATH.read_text(encoding="utf-8").casefold())
        self.assertFalse(any("brief" in path.name.casefold() for path in SKILL_ROOT.rglob("*")))

    def test_no_hard_dependency_on_sqw(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").split("---\n", 2)[2]
        self.assertNotIn("$software-quality-workflows", body)

    def test_local_links_do_not_escape_package(self) -> None:
        root = SKILL_ROOT.resolve()
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", SKILL_PATH.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("mailto:"):
                continue
            resolved = (SKILL_PATH.parent / target.split("#", 1)[0]).resolve()
            self.assertTrue(resolved.is_relative_to(root), resolved)
            self.assertTrue(resolved.is_file(), resolved)


if __name__ == "__main__":
    unittest.main()
