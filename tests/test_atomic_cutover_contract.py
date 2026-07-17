from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL_TARGETS = {
    "writing-plans": ("5.0.0", 10),
    "software-quality-workflows": ("6.0.0", 52),
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
        self.assertEqual("2.0.0", manifest["bundle_version"])
        self.assertEqual(
            [("writing-plans", "5.0.0"), ("software-quality-workflows", "6.0.0")],
            [(skill["id"], skill["version"]) for skill in manifest["skills"]],
        )
        self.assertEqual(
            ["plan-to-workflow", "workflow-plan-change-proposal"],
            manifest["cross_skill_contracts"],
        )
        self.assertEqual(
            {"current_level": "shadow", "implicit_routing_default": False, "remote_writes": False},
            manifest["activation_policy"],
        )
        self.assertEqual("frontier-engineering-bundle/1.0", generated["schema_version"])
        self.assertEqual("frontier-engineering/6.0.0+5.0.0", generated["bundle_id"])
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


if __name__ == "__main__":
    unittest.main()
