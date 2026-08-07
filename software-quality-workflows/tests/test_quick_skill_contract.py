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


def linked_markdown(path: Path) -> set[Path]:
    targets = set()
    for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        target = raw.split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (path.parent / target).resolve()
        if resolved.suffix == ".md":
            targets.add(resolved)
    return targets


class QuickSkillContractTests(unittest.TestCase):
    def test_metadata_budget_and_explicit_activation(self) -> None:
        self.assertEqual("9.0.4", frontmatter(SKILL_PATH)["metadata"]["version"])
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertLessEqual(len(skill_text.encode()), 3264)
        self.assertIn(
            "Behavior proof covers the intended change and its nearest protected "
            "control; for filtering, verify retained values and order. A one-sided "
            "check cannot support a two-sided claim.",
            skill_text,
        )
        agents = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(agents["policy"]["allow_implicit_invocation"], False)

    def test_local_links_and_legacy_runtime_absence(self) -> None:
        checker = load_static_checker()
        link_errors = [
            item for item in checker.markdown_link_errors(REPO_ROOT)
            if item["path"].startswith("software-quality-workflows/")
        ]
        legacy = checker.collect_legacy_contract(REPO_ROOT)
        self.assertEqual([], link_errors)
        self.assertEqual([], legacy["legacy_runtime_paths_present"])

    def test_reference_inventory_is_reachable_and_package_local(self) -> None:
        package_root = SKILL_ROOT.resolve()
        expected = {path.resolve() for path in (SKILL_ROOT / "references").rglob("*.md")}
        visited = set()
        pending = [SKILL_PATH.resolve()]
        while pending:
            path = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            for target in linked_markdown(path):
                self.assertTrue(target.is_relative_to(package_root), target)
                self.assertTrue(target.is_file(), target)
                pending.append(target)
        self.assertEqual(expected, expected & visited)

    def test_no_model_facing_protocol_or_state_artifact(self) -> None:
        checker = load_static_checker()
        legacy = checker.collect_legacy_contract(REPO_ROOT)
        protocol_matches = [
            item for item in legacy["legacy_protocol_matches"]
            if item["path"].startswith("software-quality-workflows/")
        ]
        machine_artifacts = [
            path for root in ("references", "templates")
            for path in (SKILL_ROOT / root).rglob("*")
            if path.is_file() and path.suffix in {".json", ".jsonl", ".yaml", ".yml"}
        ]
        self.assertEqual([], protocol_matches)
        self.assertEqual([], machine_artifacts)

    def test_references_are_plain_markdown(self) -> None:
        for path in (SKILL_ROOT / "references").rglob("*.md"):
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# "), path)


if __name__ == "__main__":
    unittest.main()
