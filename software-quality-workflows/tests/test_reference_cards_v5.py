from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
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

from _workflow_reference_cards import BUNDLE_ID, build_manifest, canonical_json_bytes, discover_cards, load_json, validate_navigation_graph  # noqa: E402
from validate_skill_contracts import validate_skill  # noqa: E402

RESOLVER_SPEC = importlib.util.spec_from_file_location(
    "workflow_resolve_reference_card", SCRIPTS / "resolve_reference_card.py"
)
assert RESOLVER_SPEC is not None and RESOLVER_SPEC.loader is not None
RESOLVER = importlib.util.module_from_spec(RESOLVER_SPEC)
RESOLVER_SPEC.loader.exec_module(RESOLVER)
resolve = RESOLVER.resolve


MANIFEST_PATH = ROOT / "registries" / "reference-cards.manifest.json"
POLICY_PATH = ROOT / "registries" / "policy-owners.json"
EDGE_GOLDEN = ROOT / "tests" / "fixtures" / "reference-navigation-edges-v5.json"


class ReferenceCardsV5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_json(MANIFEST_PATH)
        cls.by_id = {item["card_id"]: item for item in cls.manifest["cards"]}

    def _request(self, *, edge_id: str = "direct-to-owner-seam") -> dict:
        current = self.by_id["sqw.entry.direct-change"]
        return {
            "bundle_id": BUNDLE_ID,
            "current_card_id": current["card_id"],
            "current_card_hash": current["sha256"],
            "edge_id": edge_id,
            "reason": "Repository evidence does not establish a defensible owner seam.",
            "evidence_refs": ["repo:ownership@sha256:abc"],
            "facts": {},
            "active_leases": [{"card_id": current["card_id"]}],
            "active_bytes": current["bytes"],
            "context_budget_bytes": 16384,
        }

    def test_manifests_schemas_and_card_bytes_are_exact(self) -> None:
        expected, issues = build_manifest(ROOT)
        self.assertEqual([], issues)
        self.assertEqual(canonical_json_bytes(expected), MANIFEST_PATH.read_bytes())
        self.assertEqual(101, len(expected["cards"]))
        self.assertTrue(all(item["path"].startswith("references/") for item in expected["cards"]))
        self.assertFalse(any("operator/" in item["path"] for item in expected["cards"]))
        self.assertEqual([], self.by_id["sqw.control.workflow-mode-selection"]["neighbors"])
        self.assertEqual([], self.by_id["sqw.review.result-envelope"]["neighbors"])
        self.assertLessEqual(self.by_id["sqw.review.result-envelope"]["bytes"], 4096)
        hypothesis = self.by_id["sqw.diagnosis.hypothesis-and-discrimination"]
        self.assertEqual(
            [("hypothesis-to-debugger", "sqw.recipes.debugger-assisted-diagnosis", "semantic")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in hypothesis["neighbors"]],
        )
        self.assertEqual([], self.by_id["sqw.diagnosis.bugfix-transition"]["neighbors"])
        self.assertEqual([], self.by_id["sqw.recipes.debugger-assisted-diagnosis"]["neighbors"])
        for card_id in (
            "sqw.entry.closure-admission",
            "sqw.closure.baseline-qualification",
            "sqw.closure.verifier-qualification",
            "sqw.closure.candidate-search",
            "sqw.closure.signoff-and-terminal",
        ):
            self.assertEqual([], self.by_id[card_id]["neighbors"], card_id)
        self.assertEqual(
            [("stability-to-round", "sqw.runtime.stability-round", "hard")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.runtime.stability-contract"]["neighbors"]],
        )
        self.assertEqual(
            [("stability-round-to-exit", "sqw.runtime.exit-and-escalation", "hard")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.runtime.stability-round"]["neighbors"]],
        )
        for card_id in (
            "sqw.intent.spec-freeze-handoff",
            "sqw.control.repair-and-invalidation",
            "sqw.control.verifier-independence",
            "sqw.runtime.exit-and-escalation",
            "sqw.workspace.task-artifact-ownership",
            "sqw.workspace.fixture-and-snapshot-hygiene",
            "sqw.workspace.prototype-lifecycle",
            "sqw.recipes.managed-runtime-sdk-smoke",
            "sqw.recipes.dependency-lockfile-drift",
            "sqw.bridges.multi-source-synthesis",
            "sqw.bridges.source-target-gap-audit",
        ):
            self.assertEqual([], self.by_id[card_id]["neighbors"], card_id)
        self.assertEqual(
            [
                ("browser-to-live-readiness", "sqw.domain.browser.live-readiness", "hard"),
                ("browser-to-content-security", "sqw.domain.browser.content-security", "hard"),
            ],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.browser.evidence-layers"]["neighbors"]],
        )
        self.assertEqual(
            [("observability-to-health-progress", "sqw.domain.observability.health-progress-and-recovery", "semantic")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.observability.signal-design"]["neighbors"]],
        )
        for card_id in (
            "sqw.domain.browser.live-readiness",
            "sqw.domain.browser.content-security",
            "sqw.domain.observability.health-progress-and-recovery",
            "sqw.domain.security.trust-boundary-and-negatives",
        ):
            self.assertEqual([], self.by_id[card_id]["neighbors"], card_id)
        self.assertEqual(
            [
                ("architecture-to-dependency-boundary", "sqw.domain.architecture.dependency-boundary-design", "semantic"),
                ("architecture-to-alternatives", "sqw.domain.architecture.alternative-decision", "semantic"),
            ],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.architecture.module-boundary-design"]["neighbors"]],
        )
        self.assertEqual(
            [("dependency-to-alternatives", "sqw.domain.architecture.alternative-decision", "semantic")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.architecture.dependency-boundary-design"]["neighbors"]],
        )
        self.assertEqual(
            [("architecture-alternative-to-migration-proof", "sqw.domain.architecture.migration-proof", "semantic")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.architecture.alternative-decision"]["neighbors"]],
        )
        self.assertEqual(
            [("performance-to-optimization", "sqw.domain.performance.optimization-and-parity", "hard")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.performance.baseline-and-noise"]["neighbors"]],
        )
        self.assertEqual(
            [
                ("plugin-to-registration", "sqw.domain.plugin.registration-public-surface", "hard"),
                ("plugin-to-installed-surface", "sqw.domain.plugin.installed-surface-proof", "hard"),
            ],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.plugin.source-package-quality"]["neighbors"]],
        )
        self.assertEqual(
            [("plugin-registration-to-installed", "sqw.domain.plugin.installed-surface-proof", "hard")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.plugin.registration-public-surface"]["neighbors"]],
        )
        self.assertEqual(
            [("runtime-to-consistency", "sqw.domain.runtime.consistency-surfaces", "hard")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.domain.runtime.version-boundary-selection"]["neighbors"]],
        )
        for card_id in (
            "sqw.domain.architecture.migration-proof",
            "sqw.domain.performance.optimization-and-parity",
            "sqw.domain.plugin.installed-surface-proof",
            "sqw.domain.runtime.consistency-surfaces",
            "sqw.domain.source.external-authority",
        ):
            self.assertEqual([], self.by_id[card_id]["neighbors"], card_id)
        self.assertEqual(
            [
                ("delegation-to-candidate-worker", "sqw.delegation.candidate-worker-contract", "hard"),
                ("delegation-to-read-only-evidence", "sqw.delegation.read-only-evidence-contract", "hard"),
            ],
            [
                (edge["edge_id"], edge["to_card_id"], edge["edge_mode"])
                for edge in self.by_id["sqw.delegation.admission-and-slicing"]["neighbors"]
            ],
        )
        for card_id in (
            "sqw.delegation.candidate-worker-contract",
            "sqw.delegation.read-only-evidence-contract",
            "sqw.delegation.fan-in-and-integration",
        ):
            self.assertEqual([], self.by_id[card_id]["neighbors"], card_id)
        self.assertEqual(
            [("test-lifecycle-to-change", "sqw.test.lifecycle-change-and-retirement", "hard")],
            [
                (edge["edge_id"], edge["to_card_id"], edge["edge_mode"])
                for edge in self.by_id["sqw.test.lifecycle-classification-and-provenance"]["neighbors"]
            ],
        )
        for card_id in (
            "sqw.test.lifecycle-change-and-retirement",
            "sqw.test.patterns.optional-postprocess-boundary",
            "sqw.test.patterns.public-adapter-migration-proof",
            "sqw.test.patterns.cross-language-parity",
            "sqw.test.patterns.read-only-dashboard-proof",
            "sqw.test.patterns.dashboard-data-lineage",
            "sqw.test.patterns.protocol-tool-stress",
            "sqw.test.patterns.native-rewrite-parity",
            "sqw.test.patterns.retrieval-fixture-curation",
            "sqw.test.patterns.semantic-contract-upgrade",
            "sqw.test.patterns.benchmark-fixture-curation",
            "sqw.test.patterns.legacy-manifest-comparison",
        ):
            self.assertEqual([], self.by_id[card_id]["neighbors"], card_id)
        self.assertEqual(
            [("review-tier-to-execution", "sqw.review.review-execution", "hard")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.review.tier-selection"]["neighbors"]],
        )
        self.assertEqual(
            [("review-to-requirements", "sqw.review.requirements-traceability", "hard")],
            [(edge["edge_id"], edge["to_card_id"], edge["edge_mode"]) for edge in self.by_id["sqw.review.review-execution"]["neighbors"]],
        )
        for card_id in (
            "sqw.review.finding-disposition",
            "sqw.review.requirements-traceability",
            "sqw.review.rubrics.architecture-maintainability",
            "sqw.review.rubrics.adversarial-decision",
            "sqw.review.rubrics.ml-ai",
            "sqw.review.rubrics.product-outcome",
            "sqw.review.rubrics.api-consumer",
            "sqw.review.rubrics.accessibility",
            "sqw.review.rubrics.privacy-data-lifecycle",
            "sqw.review.rubrics.observability-operability",
            "sqw.review.rubrics.test-evidence",
            "sqw.review.rubrics.ci-release",
            "sqw.review.rubrics.secret-handling",
            "sqw.review.rubrics.dependency-supply-chain",
        ):
            self.assertEqual([], self.by_id[card_id]["neighbors"], card_id)
        for schema_name, instance in (
            ("policy-owners.schema.json", load_json(POLICY_PATH)),
            ("reference-cards-manifest.schema.json", self.manifest),
        ):
            schema = load_json(ROOT / "schemas" / schema_name)
            Draft202012Validator.check_schema(schema)
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(instance)))
        frontmatter_schema = load_json(ROOT / "schemas" / "reference-card-frontmatter.schema.json")
        Draft202012Validator.check_schema(frontmatter_schema)
        for card in discover_cards(ROOT):
            self.assertEqual([], list(Draft202012Validator(frontmatter_schema).iter_errors(card.metadata)), card.relative_path)
            entry = self.by_id[card.metadata["card_id"]]
            self.assertEqual(len(card.raw), entry["bytes"])
            self.assertEqual("sha256:" + sha256(card.raw).hexdigest(), entry["sha256"])

    def test_edge_golden_matches_frontmatter_and_new_graph_ignores_legacy_registry(self) -> None:
        actual = [
            {
                "source": card["card_id"],
                "edge_id": edge["edge_id"],
                "target": edge["to_card_id"],
                "mode": edge["edge_mode"],
            }
            for card in self.manifest["cards"]
            for edge in card["neighbors"]
        ]
        golden = load_json(EDGE_GOLDEN)
        self.assertEqual(sorted(golden["edges"], key=lambda item: (item["source"], item["edge_id"])), sorted(actual, key=lambda item: (item["source"], item["edge_id"])))
        for name in ("_workflow_reference_cards.py", "build_reference_manifest.py", "validate_policy_owners.py", "validate_reference_cards.py", "resolve_reference_card.py"):
            self.assertNotIn("owner-registry", (SCRIPTS / name).read_text(encoding="utf-8"), name)

    def test_p3_exit_budgets_and_retired_change_manual(self) -> None:
        self.assertFalse((ROOT / "references" / "change-execution.md").exists())
        direct = self.by_id["sqw.entry.direct-change"]
        self.assertLessEqual(direct["bytes"], 4096)
        for edge in direct["neighbors"]:
            self.assertLessEqual(direct["bytes"] + self.by_id[edge["to_card_id"]]["bytes"], 10240, edge["edge_id"])
        for card_id, card in self.by_id.items():
            if card_id.startswith("sqw.diagnosis.") or card_id in {"sqw.entry.diagnose-failure", "sqw.recipes.debugger-assisted-diagnosis"} or card_id.startswith("sqw.closure."):
                self.assertLessEqual(card["bytes"], 8192, card_id)
            self.assertNotIn("operator/", card["path"])

    def test_p4_retires_broad_test_lifecycle_and_pattern_catalogs(self) -> None:
        for relative in (
            "test-lifecycle-management.md",
            "test-patterns.md",
            "test-patterns-workflow-boundaries.md",
            "test-patterns-contract-migrations.md",
            "test-patterns-runtime-surfaces.md",
            "test-patterns-evaluation-fixtures.md",
            "architecture-module-design.md",
            "api-interface-design.md",
            "runtime-version-contracts.md",
            "performance-optimization.md",
            "plugin-quality.md",
            "plugin-installed-surface.md",
            "source-driven-implementation.md",
            "browser-runtime-verification.md",
            "observability-instrumentation.md",
            "security-hardening.md",
            "intent-and-design-discovery.md",
            "repair-and-invalidation.md",
            "verifier-kernel.md",
            "real-runtime-stability-loop.md",
            "merge-conflict-resolution.md",
            "repository-recovery.md",
            "cleanup.md",
            "workspace-artifact-hygiene.md",
            "visual-design-companion.md",
            "multi-source-markdown-synthesis.md",
            "paper-source-target-gap-audits.md",
            "managed-runtime-sdk-smoke.md",
            "dependency-lockfile-drift.md",
            "read-only-architecture-audits.md",
        ):
            self.assertFalse((ROOT / "references" / relative).exists(), relative)

    def test_resolver_returns_one_exact_card_and_rejects_stale_or_undeclared_requests(self) -> None:
        request = self._request()
        result = resolve(request, self.manifest)
        self.assertTrue(result["ok"])
        self.assertEqual({"bytes", "card_id", "path", "sha256"}, set(result["target_card"]))
        self.assertEqual("sqw.change.local-change-boundary", result["target_card"]["card_id"])

        stale = deepcopy(request)
        stale["current_card_hash"] = "sha256:" + "0" * 64
        self.assertEqual("CARD_HASH_STALE", resolve(stale, self.manifest)["error"]["code"])
        undeclared = deepcopy(request)
        undeclared["edge_id"] = "related-card"
        self.assertEqual("EDGE_NOT_DECLARED", resolve(undeclared, self.manifest)["error"]["code"])

    def test_resolver_semantic_evidence_cycle_limit_and_budget_fail_closed(self) -> None:
        request = self._request()
        no_reason = deepcopy(request)
        no_reason["reason"] = ""
        self.assertEqual("SEMANTIC_REASON_MISSING", resolve(no_reason, self.manifest)["error"]["code"])
        no_evidence = deepcopy(request)
        no_evidence["evidence_refs"] = []
        self.assertEqual("EVIDENCE_REF_MISSING", resolve(no_evidence, self.manifest)["error"]["code"])
        cycle = deepcopy(request)
        cycle["active_leases"].append({"card_id": "sqw.change.local-change-boundary"})
        self.assertEqual("AUTO_CYCLE_FORBIDDEN", resolve(cycle, self.manifest)["error"]["code"])
        limit = deepcopy(request)
        limit["active_leases"].append({"card_id": "sqw.verify.gate-selection"})
        self.assertEqual("ACTIVE_CARD_LIMIT", resolve(limit, self.manifest)["error"]["code"])
        budget = deepcopy(request)
        budget["context_budget_bytes"] = request["active_bytes"]
        self.assertEqual("CONTEXT_BUDGET_INSUFFICIENT", resolve(budget, self.manifest)["error"]["code"])

    def test_hard_edges_require_registered_true_predicate_and_cross_skill_is_denied(self) -> None:
        request = self._request(edge_id="direct-to-api-contract")
        request["reason"] = ""
        self.assertEqual("HARD_PREDICATE_FALSE", resolve(request, self.manifest)["error"]["code"])
        request["facts"] = {"public-contract-implicated": True}
        self.assertEqual("sqw.domain.api.contract-change", resolve(request, self.manifest)["target_card"]["card_id"])

        foreign = deepcopy(self.manifest)
        direct = next(item for item in foreign["cards"] if item["card_id"] == "sqw.entry.direct-change")
        direct["neighbors"][0]["to_card_id"] = "wp.profiles.brief"
        request = self._request()
        self.assertEqual("CROSS_SKILL_ARTIFACT_HANDOFF_REQUIRED", resolve(request, foreign)["error"]["code"])

    def test_navigation_graph_rejects_cycle_and_paths_beyond_three_hops(self) -> None:
        def card(card_id: str, target: str | None) -> dict:
            return {"card_id": card_id, "neighbors": [] if target is None else [{"to_card_id": target}]}

        cycle = {"cards": [card("sqw.a", "sqw.b"), card("sqw.b", "sqw.a")]}
        self.assertIn("graph.cycle", {item.code for item in validate_navigation_graph(cycle)})
        deep = {"cards": [card("sqw.a", "sqw.b"), card("sqw.b", "sqw.c"), card("sqw.c", "sqw.d"), card("sqw.d", "sqw.e"), card("sqw.e", None)]}
        self.assertIn("graph.depth", {item.code for item in validate_navigation_graph(deep)})

    def test_legacy_validator_only_allows_manifest_registered_card_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "software-quality-workflows"
            shutil.copytree(ROOT, root)
            rogue = root / "references" / "rogue" / "unregistered.md"
            rogue.parent.mkdir(parents=True)
            rogue.write_text("---\n{}\n---\n# Unregistered card\n", encoding="utf-8")

            codes = {item.code for item in validate_skill(root)}

        self.assertIn("active.nested-reference", codes)
        self.assertIn("markdown.reference-frontmatter", codes)
        self.assertTrue(
            {"reference-cards.invalid", "reference-cards.manifest-stale"} & codes,
            codes,
        )


if __name__ == "__main__":
    unittest.main()
