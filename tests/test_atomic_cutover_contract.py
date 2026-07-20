from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import stat
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_TARGETS = {
    "writing-plans": ("6.0.0", 10),
    "software-quality-workflows": ("7.0.0", 52),
}
CORE_CLOSURE = re.compile(
    r"autonomous_" + r"closure|wp\." + r"closure\.|sqw\." + r"closure\."
    + r"|closure[-_ ](?:admission|contract|phase|artifact|state|event)",
    re.IGNORECASE,
)
CORE_GRAPH = re.compile(
    r"neigh" + r"bor|max_active_" + r"neigh" + r"bors|reference-card-" + r"graph|edge-" + r"golden",
    re.IGNORECASE,
)


class AtomicCutoverContractTests(unittest.TestCase):
    @staticmethod
    def _load(path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_bundle_identity_is_the_exact_atomic_target(self) -> None:
        manifest = self._load(ROOT / "bundle-manifest.json")
        generated = self._load(ROOT / "frontier-engineering.bundle.json")
        self.assertEqual("2.0", manifest["bundle_schema_version"])
        self.assertEqual("3.0.0", manifest["bundle_version"])
        self.assertEqual(
            [("writing-plans", "6.0.0"), ("software-quality-workflows", "7.0.0")],
            [(skill["id"], skill["version"]) for skill in manifest["skills"]],
        )
        self.assertEqual(
            ["plan-to-workflow", "workflow-plan-change-proposal"],
            manifest["cross_skill_contracts"],
        )
        self.assertEqual(
            {
                "current_level": "implicit_local_pilot",
                "implicit_routing_default": True,
                "remote_writes": False,
            },
            manifest["activation_policy"],
        )
        self.assertEqual("frontier-engineering-bundle/1.0", generated["schema_version"])
        self.assertEqual("frontier-engineering/7.0.0+6.0.0", generated["bundle_id"])
        self.assertEqual(2, generated["compatible_schema_epoch"])

    def test_active_card_inventory_and_static_economy_are_exact(self) -> None:
        total_card_bytes = 0
        for skill, (version, count) in SKILL_TARGETS.items():
            with self.subTest(skill=skill):
                manifest = self._load(ROOT / skill / "registries" / "reference-cards.manifest.json")
                self.assertEqual(version, manifest["skill_version"])
                self.assertEqual(count, len(manifest["cards"]))
                self.assertTrue(all(card["bytes"] <= 8192 for card in manifest["cards"]))
                total_card_bytes += sum(card["bytes"] for card in manifest["cards"])
        self.assertLessEqual(total_card_bytes, 190000)
        self.assertLessEqual(
            (ROOT / "writing-plans" / "SKILL.md").stat().st_size
            + (ROOT / "software-quality-workflows" / "SKILL.md").stat().st_size,
            12500,
        )

    def test_core_closure_protocol_has_no_residual(self) -> None:
        residuals: list[str] = []
        for skill in SKILL_TARGETS:
            for path in sorted((ROOT / skill).rglob("*")):
                if not path.is_file() or path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if (
                    CORE_CLOSURE.search(text)
                    or CORE_GRAPH.search(text)
                    or "closure" in path.relative_to(ROOT / skill).parts
                ):
                    residuals.append(path.relative_to(ROOT).as_posix())
        for path in (ROOT / "bundle-manifest.json", ROOT / "frontier-engineering.bundle.json"):
            text = path.read_text(encoding="utf-8")
            if CORE_CLOSURE.search(text) or CORE_GRAPH.search(text):
                residuals.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], residuals)


class RuntimeSafetyContractTests(unittest.TestCase):
    def test_default_runtime_has_no_interception_or_remote_execution_surface(self) -> None:
        runtime_paths = (
            "software-quality-workflows/scripts/card_cycle.py",
            "software-quality-workflows/scripts/route_workflow.py",
            "software-quality-workflows/scripts/_workflow_reference_cards.py",
            "software-quality-workflows/scripts/_workflow_state.py",
            "software-quality-workflows/scripts/local_workflow_adapter.py",
            "writing-plans/scripts/card_cycle.py",
            "writing-plans/scripts/assess_plan_mode.py",
            "writing-plans/scripts/_writing_reference_cards.py",
            "writing-plans/scripts/_plan_state.py",
        )
        forbidden_import_roots = {
            "aiohttp", "anthropic", "boto3", "httpx", "keyring", "openai", "paramiko",
            "requests", "socket", "ssl", "urllib.request",
        }
        for relative in runtime_paths:
            path = ROOT / relative
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            self.assertTrue(forbidden_import_roots.isdisjoint(imports), relative)
            if relative.endswith("/card_cycle.py"):
                self.assertFalse("os.environ" in source, relative)
                self.assertTrue("subprocess.Popen(" in source, relative)
                self.assertFalse("subprocess.run(" in source, relative)
                self.assertTrue("selectors.DefaultSelector()" in source, relative)

        for skill in SKILL_TARGETS:
            metadata = yaml.safe_load((ROOT / skill / "agents" / "openai.yaml").read_text(encoding="utf-8"))
            self.assertEqual({"interface", "policy"}, set(metadata), skill)
            self.assertEqual({"allow_implicit_invocation"}, set(metadata["policy"]), skill)
            self.assertTrue(metadata["policy"]["allow_implicit_invocation"], skill)


class PromptInputContractTest(unittest.TestCase):
    @staticmethod
    def _regular_bytes(path: Path, maximum: int) -> bytes:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_size > maximum
        ):
            raise AssertionError(f"unsafe discovery input: {path}")
        payload = path.read_bytes()
        if len(payload) != info.st_size:
            raise AssertionError(f"discovery input changed while reading: {path}")
        return payload

    def test_isolated_prompt_input(self) -> None:
        prompt_value = os.environ.get("FRONTIER_V7V6_PROMPT_INPUT")
        skills_value = os.environ.get("FRONTIER_V7V6_DISCOVERY_SKILLS_ROOT")
        if prompt_value is None and skills_value is None:
            self.skipTest("isolated prompt-input evidence was not requested")
        self.assertIsNotNone(prompt_value)
        self.assertIsNotNone(skills_value)
        prompt_path = Path(prompt_value)
        skills_root = Path(skills_value)
        prompt_payload = self._regular_bytes(prompt_path, 8_388_608)
        prompt = json.loads(prompt_payload.decode("utf-8", errors="strict"))
        self.assertIsInstance(prompt, list)
        prompt_texts: list[str] = []
        for item in prompt:
            self.assertIsInstance(item, dict)
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if isinstance(content_item, dict) and content_item.get("type") == "input_text":
                    text = content_item.get("text")
                    self.assertIsInstance(text, str)
                    prompt_texts.append(text.replace("\r\n", "\n"))
        self.assertTrue(prompt_texts)

        root_info = skills_root.lstat()
        self.assertTrue(stat.S_ISDIR(root_info.st_mode))
        self.assertEqual(os.geteuid(), root_info.st_uid)
        self.assertEqual(set(SKILL_TARGETS), {path.name for path in skills_root.iterdir()})
        locator_text = "\n".join(prompt_texts)
        for skill, (version, card_count) in SKILL_TARGETS.items():
            skill_root = skills_root / skill
            for path in skill_root.rglob("*"):
                info = path.lstat()
                self.assertFalse(stat.S_ISLNK(info.st_mode), path)
                self.assertEqual(os.geteuid(), info.st_uid, path)
                self.assertTrue(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), path)
            skill_path = skill_root / "SKILL.md"
            frontmatter = self._regular_bytes(skill_path, 16_384).decode("utf-8", errors="strict").split("---", 2)[1]
            metadata = yaml.safe_load(frontmatter)
            self.assertEqual(skill, metadata["name"])
            self.assertEqual(version, metadata["metadata"]["version"])
            agent_metadata = yaml.safe_load(
                self._regular_bytes(skill_root / "agents" / "openai.yaml", 16_384).decode("utf-8", errors="strict")
            )
            self.assertTrue(agent_metadata["policy"]["allow_implicit_invocation"])
            manifest = json.loads(
                self._regular_bytes(skill_root / "registries" / "reference-cards.manifest.json", 262_144).decode(
                    "utf-8", errors="strict"
                )
            )
            self.assertEqual(card_count, len(manifest["cards"]))
            matches = re.findall(
                rf"^- {re.escape(skill)}:.*?\(file: ([^)]+)\)$", locator_text, flags=re.MULTILINE
            )
            self.assertEqual(1, len(matches), skill)
            locator = Path(matches[0])
            self.assertNotIn("references", locator.parts)
            self.assertEqual(skill_path.resolve(strict=True), locator.resolve(strict=True))
            for card in manifest["cards"]:
                card_text = self._regular_bytes(skill_root / card["path"], 16_384).decode(
                    "utf-8", errors="strict"
                ).replace("\r\n", "\n")
                self.assertFalse(any(card_text in text for text in prompt_texts), card["path"])


if __name__ == "__main__":
    unittest.main()
