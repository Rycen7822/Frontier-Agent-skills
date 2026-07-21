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


def headings(path: Path) -> list[str]:
    return re.findall(r"(?m)^## (.+)$", path.read_text(encoding="utf-8"))


class QuickWritingPlansTests(unittest.TestCase):
    def test_entry_metadata_budget_and_profile_boundaries(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertEqual("8.0.0", frontmatter(SKILL_PATH)["metadata"]["version"])
        self.assertLessEqual(len(SKILL_PATH.read_bytes()), 4096)
        agents = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(agents["policy"]["allow_implicit_invocation"], False)
        profiles = text.split("## Profiles", 1)[1].split("\n## ", 1)[0]
        self.assertRegex(profiles, r"(?s)Brief.*current context.*loads no profile reference")
        self.assertRegex(profiles, r"(?s)Brief.*never open a template or profile reference")
        self.assertRegex(profiles, r"(?s)Handoff.*cross a context boundary.*references/profiles/handoff\.md")
        self.assertRegex(profiles, r"(?s)Program.*multi-milestone.*references/profiles/program\.md")

    def test_templates_have_only_the_required_plan_sections(self) -> None:
        expected = {
            "brief-plan.md": ["Goal", "Non-goals", "Change scope", "Ordered steps", "Verification", "Risks and rollback"],
            "executable-handoff.md": [
                "Source identity and freshness", "Goal and non-goals", "Authority, scope, and protected work",
                "Decisions and invariants", "Ordered slices and dependencies", "Allowed writes and effects",
                "Acceptance evidence and verification", "Rollback and recovery", "Blockers and unresolved facts",
                "Exact next action",
            ],
            "program-plan.md": [
                "Identity, scope, and authority", "Outcomes and non-goals", "Decisions and invariants",
                "Phase and milestone dependency graph", "Current frontier", "Migration, rollout, and rollback",
                "Proof gates", "Temporary compatibility and removal", "Open blockers", "Next executable slice",
                "Decision lineage",
            ],
        }
        for name, required in expected.items():
            self.assertEqual(required, headings(SKILL_ROOT / "templates" / name), name)

    def test_one_canonical_output_and_unresolved_work_returns_to_sqw(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        output = text.split("## Output rules", 1)[1].split("\n## ", 1)[0]
        unresolved = text.split("## Return unresolved work", 1)[1].split("\n## ", 1)[0]
        self.assertIn("one canonical deliverable", output)
        for item in ("unclear intent", "unknown root cause", "unresolved architecture", "authority gaps", "feasibility"):
            self.assertIn(item, unresolved)
        self.assertIn("$software-quality-workflows", unresolved)

    def test_retired_runtime_and_state_surfaces_are_absent(self) -> None:
        forbidden = ("plan-state", "plan_route", "render_plan", "_plan_state", "operator/", "schemas/", "scripts/")
        for path in [SKILL_PATH, *(SKILL_ROOT / "references").rglob("*.md"), *(SKILL_ROOT / "templates").glob("*.md")]:
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                self.assertNotIn(marker, text, path)


if __name__ == "__main__":
    unittest.main()
