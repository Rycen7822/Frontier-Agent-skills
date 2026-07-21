from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import unittest

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parent
SKILL_PATH = SKILL_ROOT / "SKILL.md"


def load_static_checker():
    path = REPO_ROOT / "scripts" / "evaluate_static_contracts.py"
    spec = importlib.util.spec_from_file_location("evaluate_static_contracts", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load static contract checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not match:
        raise AssertionError(f"missing YAML frontmatter: {path}")
    value = yaml.safe_load(match.group(1))
    if not isinstance(value, dict):
        raise AssertionError(f"invalid YAML frontmatter: {path}")
    return value


class QuickSkillContractTests(unittest.TestCase):
    def test_entry_metadata_budget_and_required_sections(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertEqual("9.0.0", frontmatter(SKILL_PATH)["metadata"]["version"])
        self.assertLessEqual(len(SKILL_PATH.read_bytes()), 4096)
        headings = set(re.findall(r"(?m)^## (.+)$", text))
        self.assertTrue({
            "Scope", "Default execution", "Ask only for material blockers",
            "Evidence and test retention", "Durable escalation",
            "Optional specialist references", "Completion truth",
        } <= headings)
        agents = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(agents["policy"]["allow_implicit_invocation"], True)

    def test_links_and_removed_protocol_surfaces(self) -> None:
        checker = load_static_checker()
        link_errors = [
            item for item in checker.markdown_link_errors(REPO_ROOT)
            if item["path"].startswith("software-quality-workflows/")
        ]
        legacy = checker.collect_legacy_contract(REPO_ROOT)
        protocol_matches = [
            item for item in legacy["legacy_protocol_matches"]
            if item["path"].startswith("software-quality-workflows/")
        ]
        self.assertEqual([], link_errors)
        self.assertEqual([], legacy["legacy_runtime_paths_present"])
        self.assertEqual([], protocol_matches)

    def test_direct_is_artifact_free_and_references_are_plain_markdown(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        default_section = text.split("## Default execution", 1)[1].split("\n## ", 1)[0]
        self.assertRegex(default_section, r"(?is)Direct creates no .*workflow.*card.*state.*ledger")
        self.assertIn("Use log/blame only when release, recovery, or source freshness actually requires history", default_section)
        for path in (SKILL_ROOT / "references").rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# "), path)
            self.assertNotIn("card_id:", content)

    def test_design_discovery_has_one_runtime_and_provenance_owner(self) -> None:
        runtime = SKILL_ROOT / "operator" / "design-discovery"
        self.assertEqual([runtime / "server.cjs"], sorted(SKILL_ROOT.rglob("server.cjs")))
        self.assertTrue((runtime / "SOURCE.md").is_file())
        self.assertFalse((REPO_ROOT / "brainstorming").exists())


if __name__ == "__main__":
    unittest.main()
