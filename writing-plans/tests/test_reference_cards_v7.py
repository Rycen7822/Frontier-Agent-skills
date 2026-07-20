from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _writing_reference_cards import (  # noqa: E402
    build_manifest,
    canonical_json_bytes,
    discover_cards,
    load_json,
    parse_card,
    replace_navigation,
)


class ReferenceCardsV7Tests(unittest.TestCase):
    def test_navigation_render_preserves_frontmatter_bytes(self) -> None:
        card = parse_card(ROOT / "references" / "design" / "decision-resolution.md", ROOT)
        boundary = card.raw.find(b"\n---\n", 4) + 5
        self.assertGreaterEqual(boundary, 5)
        self.assertEqual(card.raw[:boundary], replace_navigation(card)[:boundary])

    def test_manifest_policy_schema_and_card_set_are_exact(self) -> None:
        manifest_path = ROOT / "registries" / "reference-cards.manifest.json"
        manifest = load_json(manifest_path)
        expected, issues = build_manifest(ROOT)
        self.assertEqual([], issues)
        self.assertEqual(canonical_json_bytes(expected), manifest_path.read_bytes())
        self.assertEqual(10, len(manifest["cards"]))
        self.assertEqual("7.0.0", manifest["skill_version"])
        self.assertLessEqual(sum(card["bytes"] for card in manifest["cards"]), 10 * 8192)
        for schema_name, instance in (
            ("policy-owners.schema.json", load_json(ROOT / "registries" / "policy-owners.json")),
            ("reference-cards-manifest.schema.json", manifest),
            ("decision-card-map.schema.json", load_json(ROOT / "registries" / "decision-card-map.json")),
        ):
            schema = load_json(ROOT / "schemas" / schema_name)
            Draft202012Validator.check_schema(schema)
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(instance)))
        card_schema = load_json(ROOT / "schemas" / "reference-card-frontmatter.schema.json")
        by_id = {item["card_id"]: item for item in manifest["cards"]}
        for card in discover_cards(ROOT):
            self.assertEqual([], list(Draft202012Validator(card_schema).iter_errors(card.metadata)))
            self.assertEqual("sha256:" + sha256(card.raw).hexdigest(), by_id[card.metadata["card_id"]]["sha256"])
            self.assertLessEqual(len(card.raw), 8192)

    def test_builder_rejects_orphan_mapping_and_missing_selector_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("references", "registries"):
                shutil.copytree(ROOT / name, target / name)
            (target / "tests" / "fixtures").mkdir(parents=True)
            shutil.copy2(ROOT / "tests" / "fixtures" / "decision-route-cases-v7.json", target / "tests" / "fixtures")

            decision_map = json.loads((target / "registries" / "decision-card-map.json").read_text(encoding="utf-8"))
            decision_map["decisions"].append(dict(decision_map["decisions"][0], card_id="wp.orphan.card"))
            (target / "registries" / "decision-card-map.json").write_text(json.dumps(decision_map), encoding="utf-8")
            self.assertIn("decision-map.coverage", {issue.code for issue in build_manifest(target)[1]})

            shutil.copy2(ROOT / "registries" / "decision-card-map.json", target / "registries")
            fixtures = json.loads((target / "tests" / "fixtures" / "decision-route-cases-v7.json").read_text(encoding="utf-8"))
            fixtures["near_miss_cases"].pop()
            (target / "tests" / "fixtures" / "decision-route-cases-v7.json").write_text(json.dumps(fixtures), encoding="utf-8")
            self.assertIn("decision-fixture.coverage", {issue.code for issue in build_manifest(target)[1]})

    def test_card_cycle_is_the_only_public_route_surface(self) -> None:
        self.assertTrue((SCRIPTS / "card_cycle.py").is_file())
        self.assertFalse((SCRIPTS / "resolve_reference_card.py").exists())
        policy = load_json(ROOT / "registries" / "policy-owners.json")
        owner = next(item for item in policy["policies"] if item["policy_id"] == "wp.decision.resolve")
        self.assertEqual("scripts/card_cycle.py", owner["owner_id"])

    def test_card_tools_do_not_read_sqw(self) -> None:
        for name in (
            "_writing_reference_cards.py", "build_reference_manifest.py", "validate_policy_owners.py",
            "validate_reference_cards.py", "card_cycle.py",
        ):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertNotIn("software-quality-workflows/", text)


if __name__ == "__main__":
    unittest.main()
