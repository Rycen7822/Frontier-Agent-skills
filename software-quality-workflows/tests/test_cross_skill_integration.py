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


SQW_ROOT = Path(__file__).resolve().parents[1]
WRITING_ROOT = SQW_ROOT.parent / "writing-plans"
SCRIPTS = SQW_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
WRITING_SCRIPTS = WRITING_ROOT / "scripts"
if str(WRITING_SCRIPTS) not in sys.path:
    sys.path.append(str(WRITING_SCRIPTS))

from _workflow_state import canonical_hash, load_json, load_json_lines  # noqa: E402
from reconcile_workflow import reconcile  # noqa: E402
from route_workflow import assess as assess_workflow  # noqa: E402
from validate_policy_owners import validate as validate_policy_owners  # noqa: E402
from validate_workflow_state import validate_event_stream, validate_state  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


writing_plan_state = _load_module(
    "writing_plan_state_for_integration", WRITING_ROOT / "scripts" / "_plan_state.py"
)
writing_route = _load_module(
    "writing_route_for_integration", WRITING_ROOT / "scripts" / "assess_plan_mode.py"
)

STATE_SCHEMA = load_json(SQW_ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(SQW_ROOT / "schemas" / "workflow-event.schema.json")
HANDOFF_SCHEMA = load_json(WRITING_ROOT / "schemas" / "plan-execution-handoff.schema.json")
WORKFLOW_FIXTURE = SQW_ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json"
PLAN_FIXTURE = WRITING_ROOT / "tests" / "fixtures" / "plan-state" / "valid-program.json"
EVENT_FIXTURE = SQW_ROOT / "tests" / "fixtures" / "workflow-events" / "valid-events.jsonl"
WP_ROUTE_FIXTURE = WRITING_ROOT / "tests" / "fixtures" / "decision-route-cases-v7.json"
SQW_ROUTE_FIXTURE = SQW_ROOT / "tests" / "fixtures" / "decision-route-cases-v8.json"


def _workflow() -> dict:
    return load_json(WORKFLOW_FIXTURE)


class CrossSkillIntegrationTests(unittest.TestCase):
    def test_cross_skill_routes_are_exact_local_projections_of_one_source(self) -> None:
        source = load_json(SQW_ROOT.parent / "bundle-manifest.json")["cross_skill_routes"]
        source_hash = "sha256:" + sha256(
            json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifests = {
            "software-quality-workflows": load_json(
                SQW_ROOT / "registries" / "reference-cards.manifest.json"
            ),
            "writing-plans": load_json(
                WRITING_ROOT / "registries" / "reference-cards.manifest.json"
            ),
        }
        for skill_id, manifest in manifests.items():
            projection = manifest["cross_skill_routes"]
            self.assertEqual({"source_hash", "outbound", "inbound"}, set(projection))
            self.assertEqual(source_hash, projection["source_hash"])
            self.assertEqual(
                source["routes"],
                sorted(projection["outbound"] + projection["inbound"], key=lambda row: row["route_id"]),
            )
            self.assertEqual([skill_id], [row["source_skill_id"] for row in projection["outbound"]])
            self.assertEqual([skill_id], [row["target_skill_id"] for row in projection["inbound"]])

        with tempfile.TemporaryDirectory(prefix="cross-skill-local-") as temp_dir:
            isolated = Path(temp_dir)
            for skill_id, root in (("software-quality-workflows", SQW_ROOT), ("writing-plans", WRITING_ROOT)):
                target = isolated / skill_id / "registries"
                target.mkdir(parents=True)
                shutil.copy2(root / "registries" / "reference-cards.manifest.json", target)
            self.assertFalse((isolated / "bundle-manifest.json").exists())
            for skill_id in manifests:
                local = load_json(isolated / skill_id / "registries" / "reference-cards.manifest.json")
                self.assertEqual(source_hash, local["cross_skill_routes"]["source_hash"])

    def test_plan_handoff_is_the_single_closed_execution_envelope(self) -> None:
        handoff = {
            "schema_version": "3.0",
            "handoff_id": "wp-handoff:" + "0" * 64,
            "bundle_id": "frontier-engineering/4.0.0",
            "producer": {
                "profile": "program", "card_id": "wp.profiles.handoff",
                "decision_id": "wp.select.profiles.handoff", "completion_id": "sha256:" + "1" * 64,
                "plan_id": "wp-plan:" + "a" * 64, "state_hash": "sha256:" + "2" * 64,
            },
            "source_identity": {"kind": "unversioned", "identity_hash": "sha256:" + "3" * 64},
            "scope_binding": {
                "binding_id": "sha256:" + "4" * 64, "allowed_reads": ["src/**"],
                "allowed_writes": ["src/**"], "effect_ceiling": "workspace-mutation",
                "approval_requirements": [], "publication_ceiling": "none",
            },
            "goal": "Refresh the manifest owner", "non_goals": ["Publish externally"],
            "global_invariants": [{"ref": "I-01", "statement": "Preserve manifest identity"}],
            "owner_seams": [{"owner": "P-01", "paths": ["src/**"], "resources": [], "effects": ["workspace:write"]}],
            "requirements": {
                "fact_refs": [], "decision_refs": [], "evidence_refs": ["E-01"],
                "approval_refs": [], "policy_refs": [],
            },
            "ordered_slices": [{
                "slice_id": "S-01", "node_ref": "P-01", "objective": "Refresh the owner",
                "depends_on": [], "read_set": ["src/**"], "write_set": ["src/**"],
                "effect_set": ["workspace:write"], "completion_criterion": "Focused verifier passes",
            }],
            "rollback": {"strategy": "restore_previous_state", "steps": ["Restore the prior owner"], "verifier_refs": []},
            "target_entry": {
                "skill_id": "software-quality-workflows", "route_phase": "entry",
                "required_decision_ids": ["sqw.select.control.scope-authority-and-effects"],
            },
            "unresolved_blockers": [],
        }
        validator = Draft202012Validator(HANDOFF_SCHEMA)
        self.assertEqual([], list(validator.iter_errors(handoff)))
        self.assertFalse(HANDOFF_SCHEMA["additionalProperties"])
        copied = {**handoff, "execution_state": {"status": "running"}}
        self.assertTrue(list(validator.iter_errors(copied)))

    def test_workflow_binds_namespaced_plan_refs_to_canonical_plan_hash(self) -> None:
        plan = load_json(PLAN_FIXTURE)
        plan_hash = writing_plan_state.canonical_state_hash(plan)
        workflow = _workflow()
        old_prefix = "plan:wp-plan:" + "a" * 64 + "#"
        new_prefix = f"plan:{plan['plan_id']}#"
        workflow["plan_ref"] = {
            "plan_id": plan["plan_id"],
            "artifact_ref": f"artifact:plan/{plan['plan_id']}",
            "state_ref": str(PLAN_FIXTURE),
            "content_hash": plan_hash,
        }
        for node in workflow["nodes"]:
            if node.get("plan_node_ref"):
                node["plan_node_ref"] = node["plan_node_ref"].replace(old_prefix, new_prefix)
            node["input_refs"] = [ref.replace(old_prefix, new_prefix) for ref in node["input_refs"]]
        workflow["state_hash"] = canonical_hash(workflow)
        self.assertEqual([], validate_state(workflow, STATE_SCHEMA, current_plan_hash=plan_hash))
        self.assertEqual(
            "fresh", reconcile(workflow, current_plan_hash=plan_hash, verify_artifacts=False)["status"]
        )
        stale = reconcile(
            workflow, current_plan_hash="sha256:" + "9" * 64, verify_artifacts=False
        )
        self.assertFalse(stale["resume_allowed"])
        self.assertEqual("global_or_parent_replan", stale["repair"]["repair_type"])

    def test_each_skill_advances_only_its_own_typed_decision_queue(self) -> None:
        wp_fixture = load_json(WP_ROUTE_FIXTURE)
        wp_first = writing_route.assess(
            {
                **wp_fixture["defaults"],
                "pending_decision_ids": ["wp.select.profiles.program"],
            }
        )
        self.assertEqual("wp.profiles.program", wp_first["primary_card"]["card_id"])
        wp_next = writing_route.assess(
            {
                **wp_fixture["defaults"],
                "completed_decision_ids": ["wp.select.profiles.program"],
                "available_artifact_ids": ["plan-program"],
                "just_completed_card_id": "wp.profiles.program",
                "decision_request": {
                    "decision_id": "wp.select.migration.deprecation-and-rollout",
                    "produced_by_card_id": "wp.profiles.program",
                    "produced_artifact_id": "plan-program",
                },
            }
        )
        self.assertEqual("wp.migration.deprecation-and-rollout", wp_next["primary_card"]["card_id"])

        sqw_fixture = load_json(SQW_ROUTE_FIXTURE)
        sqw_first = assess_workflow(
            {
                **sqw_fixture["defaults"],
                "pending_decision_ids": ["sqw.select.entry.direct-change"],
            }
        )
        self.assertEqual("sqw.entry.direct-change", sqw_first["primary_card"]["card_id"])
        sqw_next = assess_workflow(
            {
                **sqw_fixture["defaults"],
                "completed_decision_ids": ["sqw.select.entry.direct-change"],
                "available_artifact_ids": ["workflow-intake"],
                "just_completed_card_id": "sqw.entry.direct-change",
                "decision_request": {
                    "decision_id": "sqw.select.control.scope-authority-and-effects",
                    "produced_by_card_id": "sqw.entry.direct-change",
                    "produced_artifact_id": "workflow-intake",
                },
            }
        )
        self.assertEqual("sqw.control.scope-authority-and-effects", sqw_next["primary_card"]["card_id"])

    def test_worker_can_propose_plan_change_but_cannot_approve_or_complete(self) -> None:
        events = load_json_lines(EVENT_FIXTURE)
        proposal = deepcopy(events[1])
        proposal.update({"event_id": "evt-000099", "sequence": 99, "type": "plan_change_proposed"})
        proposal["payload"]["plan_change_ref"] = "plan-change:proposal-01"
        self.assertEqual([], validate_event_stream([proposal], EVENT_SCHEMA, require_contiguous=False))
        for event_type in ("approval_granted", "workflow_completed"):
            child = deepcopy(proposal)
            child["type"] = event_type
            child["payload"].pop("plan_change_ref", None)
            if event_type == "approval_granted":
                child["payload"]["approval_ref"] = "AP-SECURITY"
            self.assertIn(
                "workflow.actor-forbidden",
                {item.code for item in validate_event_stream([child], EVENT_SCHEMA, require_contiguous=False)},
            )

    def test_policy_registry_has_one_exact_owner_per_policy(self) -> None:
        registry = load_json(SQW_ROOT / "registries" / "policy-owners.json")
        manifest = load_json(SQW_ROOT / "registries" / "reference-cards.manifest.json")
        self.assertEqual([], validate_policy_owners(registry, manifest))
        policy_ids = [item["policy_id"] for item in registry["policies"]]
        self.assertEqual(len(policy_ids), len(set(policy_ids)))


if __name__ == "__main__":
    unittest.main()
