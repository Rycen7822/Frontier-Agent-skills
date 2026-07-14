from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest


SQW_ROOT = Path(__file__).resolve().parents[1]
WRITING_ROOT = SQW_ROOT.parent / "writing-plans"
_LONG_DOC_ENV = os.environ.get("LONG_DOCUMENT_SKILL_ROOT")
LONG_DOC_ROOT = Path(_LONG_DOC_ENV).expanduser().resolve() if _LONG_DOC_ENV else None
SCRIPTS = SQW_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import load_json, load_json_lines  # noqa: E402
from reconcile_workflow import reconcile  # noqa: E402
from route_workflow import assess as assess_workflow  # noqa: E402
from validate_owner_registry import validate_registry  # noqa: E402
import validate_skill_contracts as skill_contracts  # noqa: E402
from validate_workflow_state import validate_event_stream, validate_state  # noqa: E402


WRITING_SPEC = importlib.util.spec_from_file_location("writing_plan_state_for_integration", WRITING_ROOT / "scripts" / "_plan_state.py")
assert WRITING_SPEC is not None and WRITING_SPEC.loader is not None
writing_plan_state = importlib.util.module_from_spec(WRITING_SPEC)
sys.modules[WRITING_SPEC.name] = writing_plan_state
WRITING_SPEC.loader.exec_module(writing_plan_state)

WRITING_ROUTE_SPEC = importlib.util.spec_from_file_location("writing_route_for_integration", WRITING_ROOT / "scripts" / "assess_plan_mode.py")
assert WRITING_ROUTE_SPEC is not None and WRITING_ROUTE_SPEC.loader is not None
writing_route = importlib.util.module_from_spec(WRITING_ROUTE_SPEC)
WRITING_ROUTE_SPEC.loader.exec_module(writing_route)

STATE_SCHEMA = load_json(SQW_ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(SQW_ROOT / "schemas" / "workflow-event.schema.json")
WORKFLOW_FIXTURE = SQW_ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json"
PLAN_FIXTURE = WRITING_ROOT / "tests" / "fixtures" / "plan-state" / "valid-program.json"
EVENT_FIXTURE = SQW_ROOT / "tests" / "fixtures" / "workflow-events" / "valid-events.jsonl"


def _workflow() -> dict:
    return load_json(WORKFLOW_FIXTURE)


class CrossSkillIntegrationTests(unittest.TestCase):
    def test_workflow_binds_namespaced_plan_refs_to_canonical_plan_hash(self) -> None:
        plan = load_json(PLAN_FIXTURE)
        plan_hash = writing_plan_state.canonical_state_hash(plan)
        workflow = _workflow()
        old_prefix = "plan:plan-manifest-refresh#"
        new_prefix = f"plan:{plan['plan_id']}#"
        workflow["plan_ref"] = {
            "artifact_ref": new_prefix + "P-02",
            "state_ref": str(PLAN_FIXTURE),
            "content_hash": plan_hash,
        }
        for node in workflow["nodes"]:
            if node.get("plan_node_ref"):
                node["plan_node_ref"] = node["plan_node_ref"].replace(old_prefix, new_prefix)
            node["input_refs"] = [ref.replace(old_prefix, new_prefix) for ref in node["input_refs"]]
        self.assertEqual([], validate_state(workflow, STATE_SCHEMA, current_plan_hash=plan_hash))
        self.assertEqual("fresh", reconcile(workflow, current_plan_hash=plan_hash, verify_artifacts=False)["status"])
        stale = reconcile(workflow, current_plan_hash="sha256:" + "9" * 64, verify_artifacts=False)
        self.assertFalse(stale["resume_allowed"])
        self.assertEqual("global_or_parent_replan", stale["repair"]["repair_type"])

    def test_mismatched_plan_namespace_and_copied_plan_decisions_fail_closed(self) -> None:
        workflow = _workflow()
        workflow["nodes"][1]["plan_node_ref"] = "plan:another-plan#P-02"
        self.assertIn("workflow.plan-ref-mismatch", {item.code for item in validate_state(workflow, STATE_SCHEMA)})
        copied = _workflow()
        copied["decisions"] = [{"id": "D-01", "statement": "Workflow must not copy this."}]
        self.assertIn("workflow.schema", {item.code for item in validate_state(copied, STATE_SCHEMA)})

    def test_worker_can_propose_plan_change_but_cannot_close_or_approve(self) -> None:
        events = load_json_lines(EVENT_FIXTURE)
        proposal = deepcopy(events[1])
        proposal["event_id"] = "evt-000099"
        proposal["sequence"] = 99
        proposal["type"] = "plan_change_proposed"
        proposal["payload"]["plan_change_ref"] = "plan-change:proposal-01"
        self.assertEqual([], validate_event_stream([proposal], EVENT_SCHEMA, require_contiguous=False))
        incomplete = deepcopy(proposal)
        incomplete["payload"].pop("plan_change_ref")
        self.assertIn("workflow.event-shape", {item.code for item in validate_event_stream([incomplete], EVENT_SCHEMA, require_contiguous=False)})
        for forbidden in ("approval_granted", "workflow_closed"):
            child = deepcopy(proposal)
            child["type"] = forbidden
            self.assertIn("workflow.actor-forbidden", {item.code for item in validate_event_stream([child], EVENT_SCHEMA, require_contiguous=False)})

    def test_cross_skill_ownership_text_has_one_directional_boundaries(self) -> None:
        writing_contract = (WRITING_ROOT / "references" / "plan-state-contract.md").read_text(encoding="utf-8")
        workflow_contract = (SQW_ROOT / "references" / "workflow-state-contract.md").read_text(encoding="utf-8")
        sqw_entry = (SQW_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("SQW workflow state owns actual runs", writing_contract)
        self.assertIn("Plan state owns intended outcomes", workflow_contract)
        self.assertIn("plan_change_proposed", workflow_contract)
        self.assertIn("writing-plans` owns", sqw_entry)
        if LONG_DOC_ROOT is not None:
            long_doc = (LONG_DOC_ROOT / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("source inventory", long_doc.lower())
            self.assertIn("whole-draft", long_doc.lower())
            self.assertNotIn("M2 Sparse", long_doc)

    def test_owner_registry_has_one_normative_owner_per_policy(self) -> None:
        registry = load_json(SQW_ROOT / "references" / "owner-registry.json")
        schema = load_json(SQW_ROOT / "schemas" / "owner-registry.schema.json")
        self.assertEqual([], validate_registry(registry, schema, SQW_ROOT))
        policies = [
            policy
            for owner in registry["owners"]
            if owner["authority"] == "normative_owner"
            for policy in owner["owns"]
        ]
        self.assertEqual(len(policies), len(set(policies)))

    def test_writing_entry_does_not_reclaim_execution_cleanup_or_vcs_policy(self) -> None:
        entry = (WRITING_ROOT / "SKILL.md").read_text(encoding="utf-8").lower()
        for forbidden in ("git commit", "git add", "python -m pytest", "cleanup execution", "benchmark fixture expansion"):
            self.assertNotIn(forbidden, entry)
        self.assertIn("execution is owned by `software-quality-workflows`", entry)

    def test_sqw_entry_does_not_copy_long_document_drafting_sequence(self) -> None:
        entry = (SQW_ROOT / "SKILL.md").read_text(encoding="utf-8").lower()
        for long_doc_detail in ("source-reading ledger", "section coverage matrix", "closure_review_01.md", "segmented drafting loop"):
            self.assertNotIn(long_doc_detail, entry)
        self.assertIn("long-document-segmented-writing` owns", entry)

    def test_long_document_owner_does_not_define_plan_profiles_or_runtime_state(self) -> None:
        if LONG_DOC_ROOT is None:
            self.skipTest("LONG_DOCUMENT_SKILL_ROOT is not set")
        entry = (LONG_DOC_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for foreign_contract in ("Brief Change Card", "Executable Handoff", "M2 Sparse", "workflow-state.schema.json"):
            self.assertNotIn(foreign_contract, entry)

    def test_unknown_root_cause_routes_to_diagnosis_not_implementation_plan(self) -> None:
        plan = writing_route.assess(
            {
                **writing_route.DEFAULTS,
                "explicit_plan_request": True,
                "root_cause_status": "unknown",
            }
        )
        self.assertEqual("sqw-diagnosis", plan["route"])
        self.assertIsNone(plan["profile"])
        defaults = json.loads((SQW_ROOT / "tests" / "fixtures" / "workflow-route-cases.json").read_text(encoding="utf-8"))["defaults"]
        workflow = assess_workflow({**defaults, "task_kind": "bugfix", "root_cause_status": "unknown"})
        self.assertEqual("systematic-debugging", workflow["primary_owner"])
        self.assertNotIn("writing-plans", workflow["required_references"])

    def test_direct_route_excludes_delegation_review_and_full_authority(self) -> None:
        defaults = json.loads((SQW_ROOT / "tests" / "fixtures" / "workflow-route-cases.json").read_text(encoding="utf-8"))["defaults"]
        route = assess_workflow(defaults)
        self.assertEqual("M0_DIRECT", route["workflow_mode"])
        self.assertEqual(
            [
                "references/change-execution.md",
                "references/test-driven-development.md",
                "references/verification-discipline.md",
            ],
            route["required_references"],
        )
        self.assertFalse(any("closure" in item for item in route["required_references"]))
        for excluded in ("authority-and-scope", "delegated-development", "requesting-code-review"):
            self.assertFalse(any(excluded in item for item in route["required_references"]))

    def test_closure_vocabulary_and_hermes_frontmatter_are_compatible(self) -> None:
        plan_schema = load_json(WRITING_ROOT / "schemas" / "plan-state.schema.json")
        workflow_schema = load_json(SQW_ROOT / "schemas" / "workflow-state.schema.json")
        plan_values = set(plan_schema["$defs"]["closure"]["properties"]["epistemic_status"]["enum"])
        workflow_values = set(workflow_schema["$defs"]["closure"]["properties"]["epistemic_status"]["enum"])
        self.assertEqual(plan_values, workflow_values)
        if LONG_DOC_ROOT is not None:
            long_doc = (LONG_DOC_ROOT / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("name: long-document-segmented-writing", long_doc)
            self.assertNotIn("workflow-state.schema.json", long_doc)
        for root, expected_name in ((WRITING_ROOT, "writing-plans"), (SQW_ROOT, "software-quality-workflows")):
            metadata = skill_contracts._parse_hermes_frontmatter((root / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(expected_name, metadata["name"])
            self.assertEqual("software-development", metadata["metadata"]["hermes"]["category"])


if __name__ == "__main__":
    unittest.main()
