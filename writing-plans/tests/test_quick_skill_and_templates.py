from __future__ import annotations

from pathlib import Path
import re
import unittest

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = SKILL_ROOT / "SKILL.md"


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
    def test_entry_metadata_budget_and_activation(self) -> None:
        self.assertEqual("8.0.0", frontmatter(SKILL_PATH)["metadata"]["version"])
        self.assertLessEqual(len(SKILL_PATH.read_bytes()), 4096)
        agents = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(agents["policy"]["allow_implicit_invocation"], False)

    def test_templates_are_plain_markdown_and_brief_has_no_template(self) -> None:
        templates = SKILL_ROOT / "templates"
        self.assertFalse((templates / "brief-plan.md").exists())
        for path in templates.glob("*.md"):
            self.assertTrue(path.read_text(encoding="utf-8").startswith("# "), path)

    def test_output_contract_limits_each_task_to_one_canonical_deliverable(self) -> None:
        paragraphs = [
            paragraph for paragraph in SKILL_PATH.read_text(encoding="utf-8").split("\n\n")
            if re.search(r"\bdeliverable\b", paragraph, flags=re.IGNORECASE)
        ]
        self.assertTrue(any(
            re.search(r"(?is)\b(?:one|single)\b.*\bcanonical\b.*\bdeliverable\b", paragraph)
            for paragraph in paragraphs
        ))

    def test_runtime_and_state_surfaces_are_absent(self) -> None:
        for name in ("operator", "schemas", "scripts"):
            self.assertFalse((SKILL_ROOT / name).exists())


if __name__ == "__main__":
    unittest.main()
