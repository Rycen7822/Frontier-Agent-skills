from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import load_json  # noqa: E402
from route_workflow import assess  # noqa: E402
from validate_owner_registry import validate_registry  # noqa: E402


class WorkflowRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads((ROOT / "tests" / "fixtures" / "workflow-route-cases.json").read_text(encoding="utf-8"))

    def test_frozen_route_matrix_matches_explainable_router(self) -> None:
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                actual = assess({**self.fixture["defaults"], **case["facts"]})
                for key, expected in case["expected"].items():
                    self.assertEqual(expected, actual.get(key), (key, actual))
                self.assertEqual({**self.fixture["defaults"], **case["facts"]}["request_mode"], actual["request_mode"])
                if "durable_state_required" in case["expected"]:
                    self.assertEqual(case["expected"]["durable_state_required"], actual["durable_state_required"])

    def test_m0_and_m1_never_require_durable_graph_state(self) -> None:
        direct = assess(self.fixture["defaults"])
        trace = assess({**self.fixture["defaults"], "trace_only": True, "task_kind": "routine_change"})
        self.assertEqual("M0_DIRECT", direct["workflow_mode"])
        self.assertFalse(direct["durable_state_required"])
        self.assertEqual("M1_TRACE", trace["workflow_mode"])
        self.assertFalse(trace["durable_state_required"])

    def test_m1_shadow_preserves_direct_owner_references_and_gates(self) -> None:
        direct = assess({**self.fixture["defaults"], "task_kind": "bugfix"})
        traced = assess({**self.fixture["defaults"], "task_kind": "bugfix", "trace_only": True})
        self.assertEqual("M0_DIRECT", direct["workflow_mode"])
        self.assertEqual("M1_TRACE", traced["workflow_mode"])
        for key in ("primary_owner", "required_references", "required_gates", "must_not_load", "forbidden_actions"):
            self.assertEqual(direct[key], traced[key], key)
        self.assertEqual(direct["reason_codes"] + ["trace_only"], traced["reason_codes"])

    def test_cli_rejects_unknown_route_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "facts.json"
            source.write_text(json.dumps({"complexity_score": 99}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "route_workflow.py"), str(source)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(2, result.returncode)
        self.assertIn("unknown route facts", result.stdout)

    def test_router_rejects_malformed_facts_and_preserves_user_constraints(self) -> None:
        with self.assertRaises(ValueError):
            assess({"external_side_effect": "false"})
        with self.assertRaises(ValueError):
            assess({"independent_write_slices": -1})
        result = assess({
            "external_side_effect": True,
            "user_constraints": {"no_subagents": True, "no_external_writes": True, "max_review_rounds": 1},
        })
        self.assertEqual("M2_SPARSE", result["workflow_mode"])
        self.assertIn("user_forbids_subagents", result["reason_codes"])
        self.assertIn("user_forbids_external_writes", result["reason_codes"])
        self.assertIn("references/delegated-development.md", result["must_not_load"])
        self.assertTrue({"delegation", "external_write"}.issubset(result["forbidden_actions"]))

    def test_unknown_risk_and_resume_require_sparse_state(self) -> None:
        unknown = assess({"security_boundary": None})
        self.assertEqual("M2_SPARSE", unknown["workflow_mode"])
        self.assertIn("risk_fact_unknown", unknown["reason_codes"])
        resumed = assess({"resume_required": True})
        self.assertEqual("M2_SPARSE", resumed["workflow_mode"])
        self.assertTrue(resumed["durable_state_required"])

    def test_omitted_high_risk_facts_never_default_to_known_safe(self) -> None:
        result = assess({})
        self.assertEqual("M2_SPARSE", result["workflow_mode"])
        self.assertIn("risk_fact_unknown", result["reason_codes"])
        self.assertIn("references/authority-and-scope.md", result["required_references"])
        self.assertIn("references/change-execution.md", result["required_references"])
        slow = assess({"slow_external_job": True})
        self.assertEqual("M2_SPARSE", slow["workflow_mode"])
        self.assertIn("risk_fact_unknown", slow["reason_codes"])

    def test_owner_registry_covers_every_flat_reference_without_conflicts(self) -> None:
        registry = load_json(ROOT / "references" / "owner-registry.json")
        schema = load_json(ROOT / "schemas" / "owner-registry.schema.json")
        self.assertEqual([], validate_registry(registry, schema, ROOT))
        registered = {item["path"] for item in registry["owners"]}
        actual = {path.relative_to(ROOT).as_posix() for path in (ROOT / "references").glob("*.md")}
        self.assertEqual(actual, registered)

    def test_owner_registry_rejects_duplicate_policy_and_missing_path(self) -> None:
        registry = load_json(ROOT / "references" / "owner-registry.json")
        schema = load_json(ROOT / "schemas" / "owner-registry.schema.json")
        duplicate = deepcopy(registry)
        normative = [item for item in duplicate["owners"] if item["authority"] == "normative_owner"]
        normative[1]["owns"] = [normative[0]["owns"][0]]
        codes = {item.code for item in validate_registry(duplicate, schema, ROOT)}
        self.assertIn("registry.policy-duplicate", codes)
        missing = deepcopy(registry)
        missing["owners"][0]["path"] = "references/does-not-exist.md"
        codes = {item.code for item in validate_registry(missing, schema, ROOT)}
        self.assertIn("registry.path-missing", codes)


if __name__ == "__main__":
    unittest.main()
