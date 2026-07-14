from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import load_json  # noqa: E402
from validate_owner_registry import validate_registry  # noqa: E402


class ReferenceGraphV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_json(ROOT / "references" / "owner-registry.json")
        self.schema = load_json(ROOT / "schemas" / "owner-registry.schema.json")

    def codes(self, registry: dict[str, object]) -> set[str]:
        return {item.code for item in validate_registry(registry, self.schema, ROOT)}

    def test_registry_v2_covers_migrated_active_tree_and_central_owners(self) -> None:
        self.assertEqual("2.0", self.registry["schema_version"])
        self.assertEqual([], validate_registry(self.registry, self.schema, ROOT))
        actual = {path.relative_to(ROOT).as_posix() for path in (ROOT / "references").glob("*.md")}
        registered = {item["path"] for item in self.registry["owners"]}
        self.assertEqual(actual, registered)
        self.assertEqual(54, len(actual))
        ids = {item["id"] for item in self.registry["owners"]}
        self.assertTrue({"change-execution", "autonomous-closure", "verifier-kernel", "evidence-delegation"}.issubset(ids))
        self.assertNotIn("version-sensitive-recipes", ids)
        self.assertFalse((ROOT / "references" / "version-sensitive-recipes.md").exists())

    def test_authority_roles_and_policy_ownership_are_structural(self) -> None:
        by_id = {item["id"]: item for item in self.registry["owners"]}
        self.assertEqual("normative_owner", by_id["autonomous-closure"]["authority"])
        self.assertEqual("companion", by_id["evidence-delegation"]["authority"])
        self.assertIn("autonomous-closure-lifecycle", by_id["autonomous-closure"]["owns"])
        self.assertNotIn("owns", by_id["evidence-delegation"])
        self.assertIn("read-only-evidence-slices", by_id["evidence-delegation"]["contributes"])

    def test_companion_cannot_own_or_be_required_and_normative_cannot_contribute(self) -> None:
        companion = deepcopy(self.registry)
        row = next(item for item in companion["owners"] if item["authority"] == "companion")
        row["owns"] = ["stolen-policy"]
        self.assertIn("registry.companion-owns", self.codes(companion))

        normative = deepcopy(self.registry)
        row = next(item for item in normative["owners"] if item["authority"] == "normative_owner")
        row["contributes"] = ["question-only"]
        self.assertIn("registry.normative-contributes", self.codes(normative))

        bad_requires = deepcopy(self.registry)
        owner = next(item for item in bad_requires["owners"] if item["id"] == "autonomous-closure")
        companion_id = next(item["id"] for item in bad_requires["owners"] if item["authority"] == "companion")
        owner["requires"] = [companion_id]
        self.assertIn("registry.requires-companion", self.codes(bad_requires))

    def test_requires_cycle_conflict_asymmetry_and_unknown_edges_fail(self) -> None:
        cycle = deepcopy(self.registry)
        by_id = {item["id"]: item for item in cycle["owners"]}
        by_id["authority-and-scope"]["requires"] = ["workflow-state-contract"]
        by_id["workflow-state-contract"]["requires"] = ["authority-and-scope"]
        self.assertIn("registry.requires-cycle", self.codes(cycle))

        asymmetric = deepcopy(self.registry)
        by_id = {item["id"]: item for item in asymmetric["owners"]}
        by_id["change-execution"]["conflicts_with"] = ["read-only-architecture-audits"]
        by_id["read-only-architecture-audits"]["conflicts_with"] = []
        self.assertIn("registry.conflict-asymmetric", self.codes(asymmetric))

        unknown = deepcopy(self.registry)
        unknown["owners"][0]["may_load"] = ["missing-owner"]
        self.assertIn("registry.edge-unknown", self.codes(unknown))

        phase = deepcopy(self.registry)
        by_id = {item["id"]: item for item in phase["owners"]}
        by_id["autonomous-closure"]["requires"] = ["repository-recovery"]
        self.assertIn("registry.phase-incompatible", self.codes(phase))

        lifecycle = deepcopy(self.registry)
        by_id = {item["id"]: item for item in lifecycle["owners"]}
        by_id["change-execution"]["requires"] = ["systematic-debugging"]
        self.assertIn("registry.lifecycle-requires-lifecycle", self.codes(lifecycle))

    def test_external_owners_are_optional_probes_not_local_paths(self) -> None:
        external = self.registry["external_owners"]
        row = next(item for item in external if item["id"] == "long-document-segmented-writing")
        self.assertEqual("optional", row["availability"])
        self.assertNotIn("path", row)


if __name__ == "__main__":
    unittest.main()
