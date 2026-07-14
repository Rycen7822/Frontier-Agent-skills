from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import canonical_hash, load_json  # noqa: E402
from validate_workflow_state import validate_event_stream, validate_state, validate_transition  # noqa: E402


STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(ROOT / "schemas" / "workflow-event.schema.json")


def standard_state() -> dict:
    return load_json(ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json")


def closure_state(phase: str = "SPEC_COMPILING") -> dict:
    state = standard_state()
    state["execution_policy"] = "autonomous_closure"
    state.setdefault("policy_bundle_hash", "sha256:" + "2" * 64)
    state["mode"] = "M2_SPARSE"
    owners = [
        "authority-and-scope",
        "verifier-kernel",
        "workflow-state-contract",
        "workflow-modes",
        "verification-discipline",
    ]
    paths = {
        item["id"]: item["path"]
        for item in load_json(ROOT / "references" / "owner-registry.json")["owners"]
    }
    state["active_owners"] = {
        "primary": "autonomous-closure",
        "normative": owners,
        "companions": [],
        "loaded_references": [
            {"owner_id": owner, "path": paths[owner], "reason_code": "closure_owner_required", "phase": phase}
            for owner in ["autonomous-closure", *owners]
        ],
    }
    run = {
        "phase": phase,
        "policy_bundle_hash": state["policy_bundle_hash"],
        "budget": {
            "iterations_used": 0,
            "iterations_limit": 8,
            "candidate_evaluations_used": 0,
            "candidate_evaluations_limit": 10,
            "review_rounds_used": 0,
            "review_rounds_limit": 2,
        },
        "active_candidate_refs": [],
        "active_counterexample_refs": [],
        "terminal_status": None,
        "terminal_certificate_ref": None,
    }
    if phase != "SPEC_COMPILING":
        run["contract_ref"] = {"artifact_ref": "artifact:contract/CC-001", "content_hash": "sha256:" + "3" * 64, "epoch": 1}
    if phase in {"VERIFIER_QUALIFYING", "PLANNING", "SEARCHING", "SIGNING_OFF", "TERMINAL"}:
        run["baseline_ref"] = {"artifact_ref": "artifact:baseline/BL-001", "content_hash": "sha256:" + "4" * 64}
    if phase in {"PLANNING", "SEARCHING", "SIGNING_OFF", "TERMINAL"}:
        run["verifier_bundle_ref"] = {"artifact_ref": "artifact:verifier/VB-001", "content_hash": "sha256:" + "5" * 64, "epoch": 1}
    if phase in {"SIGNING_OFF", "TERMINAL"}:
        run["incumbent_candidate_ref"] = "artifact:candidate/C-001"
    if phase == "TERMINAL":
        run["terminal_status"] = "CLOSED"
        run["terminal_certificate_ref"] = "artifact:terminal/TC-001"
    state["closure_run"] = run
    return state


def durable_event(event_type: str = "contract_compiled", actor: str = "controller") -> dict:
    return {
        "schema_version": "1.1",
        "event_id": "evt-closure-0001",
        "workflow_id": "wf-manifest-refresh",
        "sequence": 1,
        "timestamp": "2026-07-14T12:00:00+08:00",
        "actor": {"kind": actor, "id": f"{actor}-1"},
        "type": event_type,
        "state_version": 1,
        "source_revision": "explicit-unversioned",
        "payload": {
            "classification": "internal",
            "summary": "closure event proposal",
            "artifact_refs": ["artifact:proposal/P-001"],
            "changed_refs": [],
            "side_effects_observed": [],
        },
    }


class WorkflowStateV11Tests(unittest.TestCase):
    def test_schema_is_1_1_and_requires_execution_policy_and_policy_hash(self) -> None:
        self.assertEqual("1.1", STATE_SCHEMA["properties"]["schema_version"]["const"])
        self.assertTrue({"execution_policy", "policy_bundle_hash"}.issubset(STATE_SCHEMA["required"]))
        state = standard_state()
        self.assertEqual("1.1", state["schema_version"])
        self.assertEqual("standard", state["execution_policy"])
        self.assertEqual([], validate_state(state, STATE_SCHEMA))

    def test_standard_forbids_closure_run_and_closure_requires_m2_or_m3(self) -> None:
        standard = standard_state()
        standard["closure_run"] = closure_state()["closure_run"]
        standard_codes = {item.code for item in validate_state(standard, STATE_SCHEMA)}
        self.assertIn("workflow.closure-policy", standard_codes)
        self.assertIn("workflow.schema", standard_codes)
        closure = closure_state()
        closure["mode"] = "M1_TRACE"
        self.assertIn("workflow.closure-mode", {item.code for item in validate_state(closure, STATE_SCHEMA)})
        closure = closure_state()
        closure.pop("closure_run")
        closure_codes = {item.code for item in validate_state(closure, STATE_SCHEMA)}
        self.assertIn("workflow.closure-policy", closure_codes)
        self.assertIn("workflow.schema", closure_codes)

    def test_phase_dependent_refs_reject_future_or_missing_artifacts(self) -> None:
        spec = closure_state("SPEC_COMPILING")
        spec["closure_run"]["contract_ref"] = {"artifact_ref": "artifact:contract/CC-early", "content_hash": "sha256:" + "3" * 64, "epoch": 1}
        spec_codes = {item.code for item in validate_state(spec, STATE_SCHEMA)}
        self.assertIn("workflow.closure-phase", spec_codes)
        self.assertIn("workflow.schema", spec_codes)
        for phase, field in (("CONTRACT_FROZEN", "contract_ref"), ("VERIFIER_QUALIFYING", "baseline_ref"), ("PLANNING", "verifier_bundle_ref"), ("SIGNING_OFF", "incumbent_candidate_ref"), ("TERMINAL", "terminal_certificate_ref")):
            with self.subTest(phase=phase):
                state = closure_state(phase)
                state["closure_run"].pop(field)
                self.assertIn("workflow.closure-phase", {item.code for item in validate_state(state, STATE_SCHEMA)})

    def test_active_owner_shape_matches_registry_and_reference_budget(self) -> None:
        state = closure_state("SEARCHING")
        self.assertEqual([], validate_state(state, STATE_SCHEMA))
        state["active_owners"]["companions"] = ["code-smell-checklist"]
        self.assertIn("workflow.owner-stack", {item.code for item in validate_state(state, STATE_SCHEMA)})
        state = closure_state("SEARCHING")
        state["active_owners"]["loaded_references"][0]["path"] = "references/verification-discipline.md"
        self.assertIn("workflow.owner-stack", {item.code for item in validate_state(state, STATE_SCHEMA)})

    def test_identity_policy_phase_incumbent_and_terminal_are_controller_only(self) -> None:
        previous = closure_state("PLANNING")
        current = deepcopy(previous)
        current["state_version"] += 1
        current["closure_run"]["phase"] = "SEARCHING"
        self.assertIn("workflow.controller-only", {item.code for item in validate_transition(previous, current, actor_kind="worker")})
        self.assertNotIn("workflow.controller-only", {item.code for item in validate_transition(previous, current, actor_kind="controller")})
        changed = deepcopy(previous)
        changed["state_version"] += 1
        changed["execution_policy"] = "standard"
        changed.pop("closure_run")
        self.assertIn("workflow.identity-change", {item.code for item in validate_transition(previous, changed, actor_kind="controller")})

    def test_all_state_mutation_is_controller_only_and_closure_counters_are_monotonic(self) -> None:
        previous = closure_state("PLANNING")
        node_change = deepcopy(previous)
        node_change["state_version"] += 1
        node_change["nodes"][0]["status"] = "ready"
        self.assertIn("workflow.controller-only", {item.code for item in validate_transition(previous, node_change, actor_kind="worker")})

        decreased = deepcopy(previous)
        decreased["state_version"] += 1
        previous["closure_run"]["budget"]["iterations_used"] = 2
        decreased["closure_run"]["budget"]["iterations_used"] = 1
        self.assertIn("workflow.closure-budget-transition", {item.code for item in validate_transition(previous, decreased)})
        limit_changed = deepcopy(previous)
        limit_changed["state_version"] += 1
        limit_changed["closure_run"]["budget"]["iterations_limit"] += 1
        self.assertIn("workflow.closure-budget-transition", {item.code for item in validate_transition(previous, limit_changed)})

        stale_epoch = deepcopy(previous)
        stale_epoch["state_version"] += 1
        stale_epoch["closure_run"]["contract_ref"]["epoch"] = 0
        stale_epoch["closure_run"]["verifier_bundle_ref"]["epoch"] = 0
        self.assertIn("workflow.closure-epoch-transition", {item.code for item in validate_transition(previous, stale_epoch)})

    def test_early_terminal_certificate_does_not_invent_unfrozen_artifacts(self) -> None:
        state = closure_state("TERMINAL")
        state["closure_run"]["terminal_status"] = "SPEC_UNDERDETERMINED"
        for field in ("contract_ref", "baseline_ref", "verifier_bundle_ref", "incumbent_candidate_ref"):
            state["closure_run"].pop(field, None)
        self.assertEqual([], validate_state(state, STATE_SCHEMA))

    def test_admission_events_are_preworkflow_and_durable_events_are_bound(self) -> None:
        admission = {
            "schema_version": "1.1",
            "event_id": "evt-admission-0001",
            "sequence": 1,
            "timestamp": "2026-07-14T11:59:00+08:00",
            "actor": {"kind": "controller", "id": "controller-1"},
            "type": "closure_admission_completed",
            "source_revision": "explicit-unversioned",
            "payload": {
                "classification": "internal",
                "summary": "closure admission completed",
                "artifact_refs": ["artifact:admission/A-001"],
                "changed_refs": [],
                "side_effects_observed": [],
            },
        }
        self.assertEqual([], validate_event_stream([admission], EVENT_SCHEMA))
        fake_bound = deepcopy(admission)
        fake_bound["workflow_id"] = "wf-not-created"
        fake_bound["state_version"] = 1
        fake_codes = {item.code for item in validate_event_stream([fake_bound], EVENT_SCHEMA)}
        self.assertIn("workflow.admission-event-shape", fake_codes)
        self.assertIn("workflow.event-schema", fake_codes)
        durable = durable_event()
        self.assertEqual([], validate_event_stream([durable], EVENT_SCHEMA))
        durable.pop("workflow_id")
        durable_codes = {item.code for item in validate_event_stream([durable], EVENT_SCHEMA)}
        self.assertIn("workflow.event-shape", durable_codes)
        self.assertIn("workflow.event-schema", durable_codes)

    def test_closure_event_actor_authority_rejects_worker_promotion_and_terminal(self) -> None:
        for event_type in ("candidate_promoted", "contract_frozen", "terminal_certificate_emitted"):
            with self.subTest(event_type=event_type):
                event = durable_event(event_type, actor="worker")
                self.assertIn("workflow.actor-forbidden", {item.code for item in validate_event_stream([event], EVENT_SCHEMA)})
        proposal = durable_event("candidate_created", actor="worker")
        self.assertNotIn("workflow.actor-forbidden", {item.code for item in validate_event_stream([proposal], EVENT_SCHEMA)})
        for event_type, actor in (("contract_frozen", "tool"), ("candidate_promoted", "reviewer")):
            with self.subTest(event_type=event_type, actor=actor):
                event = durable_event(event_type, actor=actor)
                self.assertIn("workflow.actor-forbidden", {item.code for item in validate_event_stream([event], EVENT_SCHEMA)})
        for event_type, actor in (("candidate_created", "tool"), ("verifier_qualified", "reviewer"), ("verifier_rejected", "reviewer")):
            with self.subTest(event_type=event_type, actor=actor):
                event = durable_event(event_type, actor=actor)
                self.assertNotIn("workflow.actor-forbidden", {item.code for item in validate_event_stream([event], EVENT_SCHEMA)})

        admission = durable_event("closure_admission_completed")
        admission.pop("workflow_id")
        admission.pop("state_version")
        admission["event_id"] = "evt-admission-after"
        admission["sequence"] = 2
        self.assertIn("workflow.event-order", {item.code for item in validate_event_stream([durable_event(), admission], EVENT_SCHEMA)})

    def test_v1_migration_is_standard_only_deterministic_and_no_overwrite(self) -> None:
        from migrate_workflow_state import migrate_state, write_migration

        v1 = deepcopy(standard_state())
        v1["schema_version"] = "1.0"
        v1.pop("execution_policy", None)
        v1.pop("policy_bundle_hash", None)
        v1["active_owners"] = {
            "primary": "planned-change",
            "domain": [],
            "evidence": ["verification-discipline"],
            "loaded_references": [{"path": "references/verification-discipline.md", "reason_code": "focused_proof_available"}],
        }
        policy_hash = "sha256:" + "9" * 64
        first, report = migrate_state(v1, policy_bundle_hash=policy_hash)
        second, second_report = migrate_state(v1, policy_bundle_hash=policy_hash)
        self.assertEqual(first, second)
        self.assertEqual(report, second_report)
        self.assertEqual("1.1", first["schema_version"])
        self.assertEqual("standard", first["execution_policy"])
        self.assertNotIn("closure_run", first)
        self.assertEqual(policy_hash, first["policy_bundle_hash"])
        self.assertEqual([], validate_state(first, STATE_SCHEMA))
        self.assertEqual(canonical_hash(first), report["new_state_hash"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v1.json"
            source.write_text(json.dumps(v1), encoding="utf-8")
            state_path, report_path = root / "v11.json", root / "report.json"
            source_link = root / "v1-link.json"
            source_link.symlink_to(source)
            with self.assertRaises(Exception):
                write_migration(source_link, state_path, report_path, policy_bundle_hash=policy_hash)
            write_migration(source, state_path, report_path, policy_bundle_hash=policy_hash)
            with self.assertRaises(Exception):
                write_migration(source, state_path, report_path, policy_bundle_hash=policy_hash)

            race_state, race_report = root / "race-state.json", root / "race-report.json"
            real_link = os.link
            calls = 0

            def collide_on_report(source_name: str | os.PathLike[str], target_name: str | os.PathLike[str]) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    Path(target_name).write_text("attacker\n", encoding="utf-8")
                    raise FileExistsError(target_name)
                real_link(source_name, target_name)

            with patch("migrate_workflow_state.os.link", side_effect=collide_on_report):
                with self.assertRaises(Exception):
                    write_migration(source, race_state, race_report, policy_bundle_hash=policy_hash)
            self.assertFalse(race_state.exists())
            self.assertEqual("attacker\n", race_report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
