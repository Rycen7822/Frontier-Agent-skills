from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _writing_reference_cards import build_manifest, canonical_json_bytes, discover_cards, load_json  # noqa: E402

RESOLVER_SPEC = importlib.util.spec_from_file_location(
    "writing_resolve_reference_card", SCRIPTS / "resolve_reference_card.py"
)
assert RESOLVER_SPEC is not None and RESOLVER_SPEC.loader is not None
RESOLVER = importlib.util.module_from_spec(RESOLVER_SPEC)
RESOLVER_SPEC.loader.exec_module(RESOLVER)
resolve = RESOLVER.resolve


EXPECTED_CARD_IDS = {
    "wp.bridges.long-document-handoff",
    "wp.closure.assumptions-and-ambiguity",
    "wp.closure.compile",
    "wp.closure.freeze-and-handoff",
    "wp.closure.hard-constraints-and-corners",
    "wp.closure.search-and-publication-policy",
    "wp.decisions.architecture-decision-record",
    "wp.design.alternative-compression",
    "wp.design.depth-selection",
    "wp.design.evidence-and-decision-ledger",
    "wp.design.planning-gate",
    "wp.economy.output-classification",
    "wp.economy.projection-and-verification",
    "wp.entry.plan-route",
    "wp.experiments.disposable-spike",
    "wp.migration.deprecation-and-rollout",
    "wp.profiles.brief",
    "wp.profiles.handoff",
    "wp.profiles.program",
    "wp.slicing.context-capsules",
    "wp.slicing.outcome-slices",
}

EXPECTED_NEIGHBORS = {
    "wp.closure.compile": [
        ("compile-to-constraints-corners", "wp.closure.hard-constraints-and-corners", "semantic"),
        ("compile-to-assumptions-ambiguity", "wp.closure.assumptions-and-ambiguity", "semantic"),
        ("compile-to-search-publication", "wp.closure.search-and-publication-policy", "semantic"),
        ("compile-to-freeze-handoff", "wp.closure.freeze-and-handoff", "hard"),
    ],
    "wp.design.depth-selection": [
        ("depth-to-evidence-ledger", "wp.design.evidence-and-decision-ledger", "hard"),
    ],
    "wp.design.evidence-and-decision-ledger": [
        ("evidence-to-alternative-compression", "wp.design.alternative-compression", "semantic"),
    ],
    "wp.design.alternative-compression": [
        ("alternatives-to-planning-gate", "wp.design.planning-gate", "hard"),
    ],
    "wp.slicing.outcome-slices": [
        ("slices-to-context-capsules", "wp.slicing.context-capsules", "hard"),
    ],
    "wp.economy.output-classification": [
        ("output-to-projection-verification", "wp.economy.projection-and-verification", "hard"),
    ],
}


class ReferenceCardsV4Tests(unittest.TestCase):
    def test_manifest_policy_schema_and_final_card_set_are_exact(self) -> None:
        manifest_path = ROOT / "registries" / "reference-cards.manifest.json"
        manifest = load_json(manifest_path)
        expected, issues = build_manifest(ROOT)
        self.assertEqual([], issues)
        self.assertEqual(canonical_json_bytes(expected), manifest_path.read_bytes())
        self.assertEqual(21, len(manifest["cards"]))
        self.assertEqual(EXPECTED_CARD_IDS, {item["card_id"] for item in manifest["cards"]})
        for schema_name, instance in (
            ("policy-owners.schema.json", load_json(ROOT / "registries" / "policy-owners.json")),
            ("reference-cards-manifest.schema.json", manifest),
        ):
            schema = load_json(ROOT / "schemas" / schema_name)
            Draft202012Validator.check_schema(schema)
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(instance)))
        card_schema = load_json(ROOT / "schemas" / "reference-card-frontmatter.schema.json")
        by_id = {item["card_id"]: item for item in manifest["cards"]}
        for card in discover_cards(ROOT):
            self.assertEqual([], list(Draft202012Validator(card_schema).iter_errors(card.metadata)))
            self.assertEqual("sha256:" + sha256(card.raw).hexdigest(), by_id[card.metadata["card_id"]]["sha256"])
        self.assertLessEqual((ROOT / "SKILL.md").stat().st_size, 6144)
        self.assertFalse([item["path"] for item in manifest["cards"] if item["path"].startswith("operator/")])
        for retired in (
            "architecture-decision-records.md",
            "closure-contract.md",
            "context-and-output-economy-plans.md",
            "deprecation-migration-plans.md",
            "design-audit-compression-ledger.md",
            "implementation-slicing-and-context-capsules.md",
            "plan-profiles.md",
            "plan-state-contract.md",
            "spike.md",
        ):
            self.assertFalse((ROOT / "references" / retired).exists(), retired)

    def test_exact_edge_golden_leaf_shape_and_resolution_fail_closed(self) -> None:
        golden = load_json(ROOT / "tests" / "fixtures" / "reference-navigation-edges-v4.json")
        manifest = load_json(ROOT / "registries" / "reference-cards.manifest.json")
        by_id = {item["card_id"]: item for item in manifest["cards"]}
        actual = [
            {"source": card["card_id"], "edge_id": edge["edge_id"], "target": edge["to_card_id"], "mode": edge["edge_mode"]}
            for card in manifest["cards"]
            for edge in card["neighbors"]
        ]
        self.assertEqual(sorted(golden["edges"], key=lambda item: (item["source"], item["edge_id"])), sorted(actual, key=lambda item: (item["source"], item["edge_id"])))
        self.assertEqual(9, len(actual))
        for card_id, expected in EXPECTED_NEIGHBORS.items():
            self.assertEqual(expected, [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in by_id[card_id]["neighbors"]])
        for card_id in EXPECTED_CARD_IDS - EXPECTED_NEIGHBORS.keys():
            self.assertEqual([], by_id[card_id]["neighbors"], card_id)

        entry = by_id["wp.profiles.brief"]
        request = {
            "bundle_id": manifest["bundle_id"], "current_card_id": entry["card_id"],
            "current_card_hash": entry["sha256"], "edge_id": "related-profile",
            "reason": "looks related", "evidence_refs": ["request:current"], "facts": {},
            "active_leases": [{"card_id": entry["card_id"]}], "active_bytes": entry["bytes"],
            "context_budget_bytes": 8192,
        }
        self.assertEqual("EDGE_NOT_DECLARED", resolve(request, manifest)["error"]["code"])

        compile_card = by_id["wp.closure.compile"]
        request.update({
            "current_card_id": compile_card["card_id"],
            "current_card_hash": compile_card["sha256"],
            "edge_id": "compile-to-freeze-handoff",
            "active_leases": [{"card_id": compile_card["card_id"]}],
            "active_bytes": compile_card["bytes"],
            "context_budget_bytes": 16384,
        })
        self.assertEqual("HARD_PREDICATE_FALSE", resolve(request, manifest)["error"]["code"])
        request["facts"] = {"closure-contract-sections-complete": True}
        self.assertEqual("wp.closure.freeze-and-handoff", resolve(request, manifest)["target_card"]["card_id"])

    def test_new_graph_tools_do_not_read_sqw_or_legacy_reference_map(self) -> None:
        for name in ("_writing_reference_cards.py", "build_reference_manifest.py", "validate_policy_owners.py", "validate_reference_cards.py", "resolve_reference_card.py"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertNotIn("owner-registry", text)
            self.assertNotIn("software-quality-workflows/", text)


if __name__ == "__main__":
    unittest.main()
