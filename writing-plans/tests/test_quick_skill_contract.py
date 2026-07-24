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
    "Resume preflight",
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
    def test_metadata_budget_and_explicit_activation(self) -> None:
        metadata = frontmatter(SKILL_PATH)
        self.assertEqual("8.0.0", metadata["metadata"]["version"])
        description = metadata["description"].casefold()
        self.assertGreaterEqual(len(description), 80)
        for term in ("source-bound", "software implementation", "handoff", "program"):
            self.assertIn(term, description)
        self.assertLessEqual(len(SKILL_PATH.read_bytes()), 4096)
        agents = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(agents["policy"]["allow_implicit_invocation"], False)

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
        self.assertIn("one combined command/evidence statement", body)

    def test_source_binding_and_first_source_change_are_distinct(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8")
        self.assertLess(
            body.index("Revision or explicit non-Git source identity"),
            body.index("Resume preflight"),
        )
        self.assertLess(
            body.index("Resume preflight"),
            body.index("Exact next source-changing action"),
        )

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
        for contract in ("before writing", "do not reopen", "git diff --check"):
            self.assertIn(contract, body)

    def test_minimal_sufficient_plan_and_execution_contract(self) -> None:
        body = SKILL_PATH.read_text(encoding="utf-8").casefold()
        for contract in (
            "minimal sufficient form",
            "repo-relative paths",
            "state each fact",
            "one combined prewrite inspection",
            "one combined final proof command",
            "at most one combined non-content confirmation",
            "do not expand one sentence into its own heading",
            "skill-authoring workflow",
            "portable identity",
            "no word/byte reduction target",
            "only one compact contract table",
            "exact first-slice inputs, outputs, values, invariants",
            "directly from settled facts once",
            "state behavior, not just a symbol/test",
            "program uses those rows",
            "exclude the named plan deliverable itself",
            "never compare against the original absolute root",
            "globally clean status",
            "exact source content already bound in the invocation",
            "prompt-named plan/owner/test/symbol paths as resolved",
            "do not inventory files, search alternate owners, or check existence separately",
            "only a later planning invocation updates the program",
            "protected immutable input",
            "do not instruct execution to modify the plan",
            "repository's test owner",
            "not an example or alternative",
            "pythondontwritebytecode=1 python -m unittest <repo-test>",
            "never use bare `pytest`",
            "leaves no cache/state artifact",
            "exact cleanup",
        ):
            self.assertIn(contract, body)
        self.assertIn("state contains current frontier and later blockers", body)
        self.assertIn("slice contains milestones in dependency order", body)

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
