from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import canonical_artifact_hash, canonical_hash, load_json  # noqa: E402
from _closure import (  # noqa: E402
    ClosureError,
    admit,
    apply_event,
    compute_invalidation,
    compute_terminal_status,
    eligible_events,
    rank_candidates,
)
from validate_verifier_bundle import canonical_bundle_hash  # noqa: E402
from validate_workflow_state import validate_state  # noqa: E402
from advance_closure import ControllerConflict, GENESIS_EVENT_HASH, _accepted_event_hash, _error_code, advance_once  # noqa: E402
from local_workflow_adapter import AdapterConflict  # noqa: E402


ARTIFACT_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "valid-artifacts.json"
VERIFIER_FIXTURE = ROOT / "tests" / "fixtures" / "verifier-bundles" / "valid-qualified.json"
REVIEW_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "valid-review-result.json"
WRITING_CONTRACT_FIXTURE = ROOT.parent / "writing-plans" / "tests" / "fixtures" / "closure-contracts" / "valid-minimal.json"
WRITING_ADMISSION_FIXTURE = ROOT.parent / "writing-plans" / "tests" / "fixtures" / "closure-contracts" / "valid-admission.json"
WRITING_AUTHORITY_FIXTURE = ROOT.parent / "writing-plans" / "tests" / "fixtures" / "closure-contracts" / "valid-authority-manifest.json"
WRITING_PLAN_FIXTURE = ROOT.parent / "writing-plans" / "tests" / "fixtures" / "plan-state" / "valid-program.json"
TRAJECTORY_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "controller-trajectories.json"
STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")


def _template_state() -> dict:
    state = load_json(ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json")
    state["execution_policy"] = "autonomous_closure"
    state["mode"] = "M2_SPARSE"
    state["request_mode"] = "change"
    normative = ["authority-and-scope", "verifier-kernel", "workflow-mode-selection", "workflow-modes", "verification-discipline"]
    state["active_owners"] = {
        "primary": "autonomous-closure",
        "normative": normative,
        "companions": [],
    }
    state["scope"].update({
        "allowed_reads": ["src/**", "tests/**"],
        "allowed_writes": ["src/manifest/**", "tests/manifest/**", "src/payments/**", "tests/payments/**"],
        "protected_paths": ["docs/private/**", ".closure/**", "tests/protected/**"],
    })
    return state


def _handoff_artifacts(state: dict) -> tuple[dict, dict, dict]:
    admission = load_json(WRITING_ADMISSION_FIXTURE)
    authority = load_json(WRITING_AUTHORITY_FIXTURE)
    authority.update({
        "request_mode": "change",
        "source_revision": state["source"]["base_revision"],
        "scope_hash": state["source"]["scope_hash"],
        "autonomy_ceiling": state["authority"]["risk_ceiling"],
    })
    admission_hash = canonical_artifact_hash(admission)
    authority_hash = canonical_artifact_hash(authority)
    contract = load_json(WRITING_CONTRACT_FIXTURE)
    contract.update({
        "contract_id": "CC-001",
        "epoch": 1,
        "status": "frozen",
        "frozen_at": "2026-07-14T00:01:00Z",
        "bundle_id": state["bundle_id"],
        "closure_admission_ref": f"artifact:admission/{admission['admission_id']}",
        "closure_admission_hash": admission_hash,
        "authority_manifest_ref": f"artifact:authority/{authority['manifest_id']}",
        "authority_manifest_hash": authority_hash,
    })
    contract["source"].update({
        "repository": state["source"]["repository"],
        "base_revision": state["source"]["base_revision"],
        "scope_hash": state["source"]["scope_hash"],
        "policy_bundle_hash": state["policy_bundle_hash"],
        "reference_manifest_hash": state["card_manifest_hash"],
    })
    contract["authority"].update({"request_mode": "change", "autonomy_ceiling": state["authority"]["risk_ceiling"]})
    contract["scope"].update({
        "scope_hash": state["source"]["scope_hash"],
        "allowed_read_paths": state["scope"]["allowed_reads"],
        "allowed_write_paths": state["scope"]["allowed_writes"],
        "forbidden_paths": state["scope"]["protected_paths"],
    })
    contract["protected_surfaces"] = [
        {"id": f"PS-{index:03d}", "path": path, "protection": "controller_owned", "source_anchors": ["policy:closure-kernel#protected-surface"]}
        for index, path in enumerate(state["scope"]["protected_paths"], 1)
    ]
    contract["content_hash"] = canonical_artifact_hash(contract)
    return admission, authority, contract


def closure_state(phase: str = "BASELINING") -> dict:
    state = _template_state()
    admission, authority, contract = _handoff_artifacts(state)
    state["closure_run"] = {
        "phase": phase,
        "policy_bundle_hash": state["policy_bundle_hash"],
        "handoff_ref": {"artifact_ref": "artifact:handoff/handoff-0123456789abcdefabcd", "content_hash": "sha256:" + "5" * 64},
        "admission_ref": {"artifact_ref": contract["closure_admission_ref"], "content_hash": canonical_artifact_hash(admission)},
        "authority_manifest_ref": {"artifact_ref": contract["authority_manifest_ref"], "content_hash": canonical_artifact_hash(authority)},
        "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": contract["content_hash"], "epoch": 1},
        "active_candidate_refs": [],
        "active_counterexample_refs": [],
        "budget": {"iterations_used": 0, "iterations_limit": 8, "candidate_evaluations_used": 0, "candidate_evaluations_limit": 10, "review_rounds_used": 0, "review_rounds_limit": 2},
        "terminal_status": None,
        "terminal_certificate_ref": None,
    }
    state.pop("state_hash", None)
    state["state_hash"] = canonical_hash(state)
    return state


def controller_event(state: dict, event_type: str, *, refs: list[str] | None = None, actor: str = "controller", **payload_fields: object) -> dict:
    sequence = state["state_version"] - 2
    payload = {"classification": "internal", "summary": event_type, "artifact_refs": refs or [], "changed_refs": [], "side_effects_observed": [], **payload_fields}
    return {
        "schema_version": "1.1",
        "event_id": f"evt-{sequence:04d}-{event_type}",
        "workflow_id": state["workflow_id"],
        "sequence": sequence,
        "timestamp": f"2026-07-14T12:{sequence:02d}:00+08:00",
        "actor": {"kind": actor, "id": f"{actor}-1"},
        "type": event_type,
        "state_version": state["state_version"] + 1,
        "source_revision": state["source"]["observed_revision"],
        "payload": payload,
    }


def artifact_map() -> dict[str, dict]:
    values = load_json(ARTIFACT_FIXTURE)
    by_type = {item["schema_id"].split("/")[-2]: item for item in values}
    template_state = _template_state()
    workflow_id = template_state["workflow_id"]
    scope_hash = template_state["source"]["scope_hash"]
    admission, authority, contract = _handoff_artifacts(template_state)
    contract_hash = contract["content_hash"]
    verifier = load_json(VERIFIER_FIXTURE)
    verifier["closure_epoch"] = 1
    verifier["contract_hash"] = contract_hash
    verifier["source_revision"] = "explicit-unversioned"
    verifier["scope_hash"] = scope_hash
    verifier["oracles"] = [verifier["oracles"][0]]
    verifier["oracles"][0]["corner_refs"] = ["CORNER-LOCAL-001"]
    verifier["qualification_summary"].update({
        "required_oracle_ids": ["ORACLE-BEHAVIOR-001"],
        "qualified_oracle_ids": ["ORACLE-BEHAVIOR-001"],
        "unqualified_oracle_ids": [],
        "independence_evidence_refs": [],
    })
    verifier["protected_paths"] = sorted(set(verifier["protected_paths"]) | set(template_state["scope"]["protected_paths"]))
    verifier["content_hash"] = canonical_bundle_hash(verifier)
    verifier_hash = verifier["content_hash"]
    for item in values:
        if item["workflow_id"] != "not_created":
            item["workflow_id"] = workflow_id
            item["scope_hash"] = scope_hash
            item["contract_hash"] = contract_hash
            item["verifier_bundle_hash"] = "not_frozen" if item["schema_id"].endswith("baseline-result/1.0") else verifier_hash
            if item["schema_id"].endswith("candidate-manifest/1.0"):
                item["payload"]["protected_paths"] = sorted(set(template_state["scope"]["protected_paths"]) | set(verifier["protected_paths"]))
            if item["schema_id"].endswith("candidate-evaluation/1.0"):
                item["payload"]["hard_constraint_results"] = [{"id": "HC-001", "status": "pass", "evidence_refs": ["artifact:evidence/EV-HC-PASS"]}]
            if item["schema_id"].endswith("signoff-result/1.0"):
                item["payload"]["freshness"]["scope_hash"] = scope_hash
                item["payload"]["freshness"]["contract_hash"] = contract_hash
                item["payload"]["freshness"]["verifier_bundle_hash"] = verifier_hash
            item["content_hash"] = canonical_artifact_hash(item)
    by_type["signoff-result"]["payload"]["candidate_hash"] = by_type["candidate-manifest"]["content_hash"]
    by_type["signoff-result"]["payload"]["required_gate_results"] = [{
        "gate_id": "GATE-UNIT", "status": "pass", "evidence_refs": ["artifact:evidence/EV-GATE"],
    }]
    review_hash = canonical_artifact_hash(review_artifact(template_state, by_type["candidate-manifest"]))
    by_type["signoff-result"]["payload"]["axes"]["requirements"]["review_result_hash"] = review_hash
    by_type["signoff-result"]["payload"]["axes"]["engineering"]["review_result_hash"] = review_hash
    by_type["signoff-result"]["content_hash"] = canonical_artifact_hash(by_type["signoff-result"])
    terminal = deepcopy(by_type["terminal-certificate"])
    terminal.update({"workflow_id": workflow_id, "closure_epoch": 1, "scope_hash": scope_hash, "contract_hash": contract_hash, "verifier_bundle_hash": verifier_hash})
    terminal["payload"].update({
        "terminal_status": "CLOSED", "summary": "All four axes and required gates passed.", "blocking_items": [], "evidence_refs": ["artifact:signoff/SO-007"],
        "minimal_missing_information": [], "minimal_unsat_core": [], "attempted_strategies": ["SF-002"],
        "budget_consumed": {"iterations": 0, "candidate_evaluations": 1, "review_rounds": 1},
        "preserved_artifacts": ["artifact:candidate/C-007"], "safe_next_action": "Retain signed artifacts; publication remains separately authorized.",
        "source_revision": "explicit-unversioned", "scope_hash": scope_hash, "contract_hash": contract_hash, "verifier_bundle_hash": verifier_hash,
        "incumbent_candidate_ref": "artifact:candidate/C-007", "signoff_result_ref": "artifact:signoff/SO-007",
        "required_gate_result_refs": ["artifact:evidence/EV-GATE"], "residual_risk_refs": [], "publication_state_ref": "artifact:publication/PUB-001",
    })
    terminal["content_hash"] = canonical_artifact_hash(terminal)
    return {
        contract["closure_admission_ref"]: admission,
        contract["authority_manifest_ref"]: authority,
        "artifact:contract/CC-001": contract,
        "artifact:baseline/BL-001": by_type["baseline-result"],
        "artifact:verifier/VB-001": verifier,
        "artifact:candidate/C-007": by_type["candidate-manifest"],
        "artifact:evaluation/CEVAL-007": by_type["candidate-evaluation"],
        "artifact:counterexample/CE-019": by_type["counterexample"],
        "artifact:signoff/SO-007": by_type["signoff-result"],
        "artifact:terminal/TC-CLOSED": terminal,
    }


def supersession_artifact_map(epoch: int = 2) -> tuple[dict[str, dict], list[str]]:
    artifacts = artifact_map()
    state = _template_state()
    admission = deepcopy(artifacts["artifact:admission/admission-0123456789abcdefabcd"])
    admission["admission_id"] = "admission-fedcba9876543210fedc"
    admission_ref = f"artifact:admission/{admission['admission_id']}"
    authority = deepcopy(artifacts["artifact:authority/auth-0123456789abcdefabcd"])
    authority["manifest_id"] = "auth-fedcba9876543210fedc"
    authority_ref = f"artifact:authority/{authority['manifest_id']}"
    plan = load_json(WRITING_PLAN_FIXTURE)
    plan["plan_id"] = "plan-manifest-refresh-20260715"
    plan["source"].update({
        "repository": state["source"]["repository"],
        "base_revision": state["source"]["base_revision"],
        "scope_hash": state["source"]["scope_hash"],
        "bundle_id": state["bundle_id"],
        "policy_bundle_hash": state["policy_bundle_hash"],
        "reference_manifest_hash": state["card_manifest_hash"],
    })
    plan["scope"].update({
        "allowed_reads": state["scope"]["allowed_reads"],
        "allowed_writes": state["scope"]["allowed_writes"],
        "protected_paths": state["scope"]["protected_paths"],
        "risk_ceiling": state["authority"]["risk_ceiling"],
    })
    plan["content_hash"] = canonical_artifact_hash(plan)
    plan_ref = f"artifact:plan/{plan['plan_id']}"
    contract = deepcopy(artifacts["artifact:contract/CC-001"])
    contract.update({
        "contract_id": "CC-002",
        "epoch": epoch,
        "closure_admission_ref": admission_ref,
        "closure_admission_hash": canonical_artifact_hash(admission),
        "authority_manifest_ref": authority_ref,
        "authority_manifest_hash": canonical_artifact_hash(authority),
    })
    contract["content_hash"] = canonical_artifact_hash(contract)
    contract_ref = "artifact:contract/CC-002"
    handoff = {
        "schema_version": "1.0",
        "handoff_id": "handoff-fedcba9876543210fedc",
        "bundle_id": state["bundle_id"],
        "source_revision": state["source"]["base_revision"],
        "execution_policy": "autonomous_closure",
        "profile": "program",
        "closure_admission_ref": admission_ref,
        "closure_admission_hash": canonical_artifact_hash(admission),
        "plan_ref": plan_ref,
        "plan_hash": plan["content_hash"],
        "closure_contract_ref": contract_ref,
        "closure_contract_hash": contract["content_hash"],
        "authority_manifest_ref": authority_ref,
        "scope_hash": state["source"]["scope_hash"],
        "frontier_node_ids": plan["current_frontier"],
        "required_execution_policy_ids": ["sqw.change.lifecycle", "sqw.verify.completion-evidence"],
        "unresolved_blockers": [],
    }
    handoff_ref = f"artifact:handoff/{handoff['handoff_id']}"
    artifacts.update({
        admission_ref: admission,
        authority_ref: authority,
        plan_ref: plan,
        contract_ref: contract,
        handoff_ref: handoff,
    })
    return artifacts, [handoff_ref, admission_ref, plan_ref, contract_ref]


def trajectory_artifacts() -> dict[str, dict]:
    artifacts = artifact_map()
    state = closure_state()

    failed = deepcopy(artifacts["artifact:evaluation/CEVAL-007"])
    failed["artifact_id"] = "CEVAL-007-FAIL"
    failed["payload"]["hard_constraint_results"] = [{
        "id": "HC-001", "status": "fail", "evidence_refs": ["artifact:evidence/EV-HC-FAIL"],
    }]
    failed["payload"]["eligible_for_promotion"] = False
    failed["content_hash"] = canonical_artifact_hash(failed)
    artifacts["artifact:evaluation/CEVAL-007-FAIL"] = failed

    candidate8 = deepcopy(artifacts["artifact:candidate/C-007"])
    candidate8["artifact_id"] = "CM-008"
    candidate8["payload"].update({
        "candidate_id": "C-008",
        "parent": "C-007",
        "worktree_ref": "artifact:worktree/WT-008",
        "base_candidate_hash": artifacts["artifact:candidate/C-007"]["content_hash"],
        "patch_hash": "sha256:" + "8" * 64,
    })
    candidate8["content_hash"] = canonical_artifact_hash(candidate8)
    artifacts["artifact:candidate/C-008"] = candidate8

    evaluation8 = deepcopy(artifacts["artifact:evaluation/CEVAL-007"])
    evaluation8["artifact_id"] = "CEVAL-008"
    evaluation8["payload"].update({
        "candidate_id": "C-008",
        "parent_candidate_ref": "C-007",
        "patch_hash": candidate8["payload"]["patch_hash"],
        "worktree_ref": candidate8["payload"]["worktree_ref"],
        "eligible_for_promotion": True,
    })
    evaluation8["content_hash"] = canonical_artifact_hash(evaluation8)
    artifacts["artifact:evaluation/CEVAL-008"] = evaluation8

    signoff8 = deepcopy(artifacts["artifact:signoff/SO-007"])
    signoff8["artifact_id"] = "SO-008"
    signoff8["payload"].update({"candidate_ref": "artifact:candidate/C-008", "candidate_hash": candidate8["content_hash"]})
    review_hash = canonical_artifact_hash(review_artifact(state, candidate8))
    signoff8["payload"]["axes"]["requirements"]["review_result_hash"] = review_hash
    signoff8["payload"]["axes"]["engineering"]["review_result_hash"] = review_hash
    signoff8["content_hash"] = canonical_artifact_hash(signoff8)
    artifacts["artifact:signoff/SO-008"] = signoff8

    closed8 = deepcopy(artifacts["artifact:terminal/TC-CLOSED"])
    closed8["artifact_id"] = "TC-CLOSED-008"
    closed8["payload"].update({
        "evidence_refs": ["artifact:signoff/SO-008"],
        "preserved_artifacts": ["artifact:candidate/C-008"],
        "incumbent_candidate_ref": "artifact:candidate/C-008",
        "signoff_result_ref": "artifact:signoff/SO-008",
        "budget_consumed": {"iterations": 0, "candidate_evaluations": 2, "review_rounds": 1},
    })
    closed8["content_hash"] = canonical_artifact_hash(closed8)
    artifacts["artifact:terminal/TC-CLOSED-008"] = closed8

    frozen_verifier = deepcopy(artifacts["artifact:verifier/VB-001"])
    frozen_verifier["bundle_id"] = "VB-REJECT"
    frozen_verifier["status"] = "frozen"
    frozen_verifier["qualification_summary"].update({
        "status": "inconclusive",
        "qualified_oracle_ids": [],
        "unqualified_oracle_ids": frozen_verifier["qualification_summary"]["required_oracle_ids"],
        "discrimination_evidence_refs": [],
        "independence_evidence_refs": [],
    })
    frozen_verifier["limitations"] = ["Qualification did not establish a stable discriminating oracle."]
    frozen_verifier["content_hash"] = canonical_bundle_hash(frozen_verifier)
    artifacts["artifact:verifier/VB-REJECT"] = frozen_verifier

    raw = next(item for item in load_json(ARTIFACT_FIXTURE) if item["schema_id"].endswith("terminal-certificate/1.0"))

    def failure(ref: str, status: str, *, verifier_ref: str | None = "artifact:verifier/VB-001", revision: str | None = None) -> dict:
        item = deepcopy(raw)
        durable = status not in {"SPEC_UNDERDETERMINED", "SPEC_UNSAT"}
        source_revision = revision or state["source"]["observed_revision"]
        verifier_hash = artifacts[verifier_ref]["content_hash"] if durable and verifier_ref else "not_frozen"
        contract_hash = artifacts["artifact:contract/CC-001"]["content_hash"] if durable else "not_frozen"
        item.update({
            "artifact_id": ref.rsplit("/", 1)[-1],
            "workflow_id": state["workflow_id"],
            "closure_epoch": 1 if durable else 0,
            "source_revision": source_revision,
            "scope_hash": state["source"]["scope_hash"],
            "contract_hash": contract_hash,
            "verifier_bundle_hash": verifier_hash,
        })
        evidence_ref = f"artifact:evidence/EV-{status}"
        item["payload"].update({
            "terminal_status": status,
            "summary": f"Synthetic terminal trajectory for {status}.",
            "blocking_items": [status.lower()],
            "evidence_refs": [evidence_ref],
            "minimal_missing_information": ["authoritative intent"] if status == "SPEC_UNDERDETERMINED" else [],
            "minimal_unsat_core": ["HC-001", "HC-002"] if status == "SPEC_UNSAT" else [],
            "attempted_strategies": ["SF-001"] if status == "BUDGET_EXHAUSTED" else [],
            "budget_consumed": {"iterations": 8, "candidate_evaluations": 0, "review_rounds": 0} if status == "BUDGET_EXHAUSTED" else {},
            "preserved_artifacts": [],
            "safe_next_action": "Preserve evidence and follow the typed recovery policy.",
            "source_revision": source_revision,
            "scope_hash": state["source"]["scope_hash"],
            "contract_hash": contract_hash,
            "verifier_bundle_hash": verifier_hash,
        })
        item["content_hash"] = canonical_artifact_hash(item)
        return item

    artifacts["artifact:terminal/TC-VERIFIER"] = failure("artifact:terminal/TC-VERIFIER", "VERIFIER_UNQUALIFIED", verifier_ref="artifact:verifier/VB-REJECT")
    artifacts["artifact:terminal/TC-SPEC-UNDER"] = failure("artifact:terminal/TC-SPEC-UNDER", "SPEC_UNDERDETERMINED", verifier_ref=None)
    artifacts["artifact:terminal/TC-SPEC-UNSAT"] = failure("artifact:terminal/TC-SPEC-UNSAT", "SPEC_UNSAT", verifier_ref=None)
    artifacts["artifact:terminal/TC-BUDGET"] = failure("artifact:terminal/TC-BUDGET", "BUDGET_EXHAUSTED")
    artifacts["artifact:terminal/TC-DRIFT"] = failure("artifact:terminal/TC-DRIFT", "ABORTED_BY_SOURCE_DRIFT", revision="revision-after-drift")
    artifacts["artifact:terminal/TC-WORKFLOW-INVALID"] = failure("artifact:terminal/TC-WORKFLOW-INVALID", "WORKFLOW_INVALID")
    return artifacts


def write_artifact(root: Path, ref: str, value: dict) -> Path:
    kind, artifact_id = ref.removeprefix("artifact:").split("/", 1)
    path = root / kind / f"{artifact_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def drift_terminal(revision: str = "revision-after-drift") -> dict:
    terminal = deepcopy(artifact_map()["artifact:terminal/TC-CLOSED"])
    terminal["artifact_id"] = "TC-DRIFT"
    terminal["source_revision"] = revision
    payload = terminal["payload"]
    payload.update({
        "terminal_status": "ABORTED_BY_SOURCE_DRIFT",
        "summary": "The observed source changed during the closure run.",
        "blocking_items": ["source revision changed"],
        "evidence_refs": ["artifact:evidence/EV-DRIFT"],
        "preserved_artifacts": [],
        "budget_consumed": {},
        "source_revision": revision,
        "safe_next_action": "Start a new closure epoch from the observed revision.",
    })
    for field in ("incumbent_candidate_ref", "signoff_result_ref", "required_gate_result_refs", "residual_risk_refs", "publication_state_ref"):
        payload.pop(field, None)
    terminal["content_hash"] = canonical_artifact_hash(terminal)
    return terminal


def generic_artifact(state: dict, ref: str) -> dict:
    value = {
        "schema_id": "sqw://artifact-envelope/1.0",
        "artifact_id": ref.rsplit("/", 1)[-1],
        "workflow_id": state["workflow_id"],
        "source_revision": state["source"]["observed_revision"],
        "scope_hash": state["source"]["scope_hash"],
        "created_at": "2026-07-14T12:00:00+08:00",
        "producer": {"actor": "tool", "run_id": "RUN-support"},
        "classification": "internal",
        "mime_type": "application/json",
        "command_ref": "command:synthetic-fixture",
        "redaction_policy": "none_required",
        "content_hash": "sha256:" + "0" * 64,
        "payload": {"summary": f"Supporting fixture for {ref}."},
    }
    value["content_hash"] = canonical_artifact_hash(value)
    return value


def review_artifact(state: dict, candidate: dict) -> dict:
    value = load_json(REVIEW_FIXTURE)
    payload = candidate["payload"]
    value.update({
        "reviewed_base_sha": payload["base_candidate_hash"],
        "reviewed_head_sha": payload["patch_hash"],
        "reviewed_scope_hash": state["source"]["scope_hash"],
    })
    for finding in value["findings"]:
        finding["source_revision"] = payload["patch_hash"]
    for note in value.get("positive_notes", []):
        note["source_revision"] = payload["patch_hash"]
    return value


def nested_artifact_refs(value: object) -> set[str]:
    if isinstance(value, str):
        return {value} if value.startswith("artifact:") and "/" in value.removeprefix("artifact:") else set()
    if isinstance(value, dict):
        return set().union(*(nested_artifact_refs(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(nested_artifact_refs(item) for item in value)) if value else set()
    return set()


def write_artifact_graph(root: Path, state: dict, roots: set[str], artifacts: dict[str, dict]) -> None:
    pending = list(roots)
    written: set[str] = set()
    while pending:
        ref = pending.pop(0)
        if ref in written:
            continue
        if ref in artifacts:
            value = deepcopy(artifacts[ref])
        elif ref.startswith("artifact:review/"):
            incumbent = state.get("closure_run", {}).get("incumbent_candidate_ref")
            candidate = artifacts.get(incumbent)
            if not isinstance(candidate, dict):
                raise AssertionError(f"review fixture has no incumbent candidate: {ref}")
            value = review_artifact(state, candidate)
        else:
            value = generic_artifact(state, ref)
        write_artifact(root, ref, value)
        written.add(ref)
        pending.extend(sorted(nested_artifact_refs(value) - written))


class ClosureControllerTests(unittest.TestCase):
    def test_phase_eligible_events_prevent_skips_and_controller_only_acceptance(self) -> None:
        state = closure_state()
        self.assertIn("baseline_qualified", eligible_events(state))
        self.assertNotIn("verifier_qualified", eligible_events(state))
        with self.assertRaises(ClosureError):
            apply_event(state, controller_event(state, "verifier_qualified", refs=["artifact:verifier/VB-001"]), artifact_map())
        with self.assertRaises(ClosureError):
            apply_event(state, controller_event(state, "baseline_qualified", refs=["artifact:baseline/BL-001"], actor="worker"), artifact_map())

    def test_single_candidate_full_trace_is_deterministic_and_closes_only_after_signoff(self) -> None:
        def replay() -> dict:
            state = closure_state()
            artifacts = artifact_map()
            steps = [
                ("baseline_qualified", ["artifact:baseline/BL-001"], {}),
                ("verifier_bundle_frozen", ["artifact:verifier/VB-001"], {}),
                ("verifier_qualified", ["artifact:verifier/VB-001"], {}),
                ("candidate_created", ["artifact:candidate/C-007"], {}),
                ("candidate_evaluated", ["artifact:evaluation/CEVAL-007"], {}),
                ("candidate_promoted", ["artifact:candidate/C-007", "artifact:evaluation/CEVAL-007"], {}),
                ("signoff_started", [], {}),
                ("signoff_completed", ["artifact:signoff/SO-007"], {}),
                ("terminal_certificate_emitted", ["artifact:terminal/TC-CLOSED"], {}),
            ]
            for event_type, refs, fields in steps:
                state = apply_event(state, controller_event(state, event_type, refs=refs, **fields), artifacts)
                self.assertEqual([], validate_state(state, STATE_SCHEMA), event_type)
            return state

        first, second = replay(), replay()
        self.assertEqual(first, second)
        self.assertEqual("TERMINAL", first["closure_run"]["phase"])
        self.assertEqual("CLOSED", first["closure_run"]["terminal_status"])
        self.assertEqual("artifact:candidate/C-007", first["closure_run"]["incumbent_candidate_ref"])
        self.assertEqual(first["state_hash"], canonical_hash(first))

    def test_counterexample_repair_and_budget_hard_stop_are_explicit(self) -> None:
        state = closure_state("SEARCHING")
        artifacts = artifact_map()
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
        })
        state["state_hash"] = canonical_hash(state)
        state = apply_event(state, controller_event(state, "counterexample_observed", refs=["artifact:counterexample/CE-019"]), artifacts)
        self.assertEqual(["artifact:counterexample/CE-019"], state["closure_run"]["active_counterexample_refs"])
        state = apply_event(state, controller_event(state, "budget_consumed", budget_delta={"iterations": 8, "candidate_evaluations": 0, "review_rounds": 0}), artifacts)
        self.assertEqual("BUDGET_EXHAUSTED", compute_terminal_status(state))
        with self.assertRaises(ClosureError):
            apply_event(state, controller_event(state, "candidate_created", refs=["artifact:candidate/C-007"]), artifacts)

    def test_last_allowed_evaluation_and_review_can_finish_but_cannot_start_more_work(self) -> None:
        artifacts = artifact_map()
        state = closure_state("SEARCHING")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
            "active_candidate_refs": ["artifact:candidate/C-007"],
        })
        state["closure_run"]["budget"]["candidate_evaluations_limit"] = 1
        state["closure_run"]["budget"]["review_rounds_limit"] = 1
        state["state_hash"] = canonical_hash(state)

        state = apply_event(state, controller_event(state, "candidate_evaluated", refs=["artifact:evaluation/CEVAL-007"]), artifacts)
        self.assertIsNone(compute_terminal_status(state))
        self.assertIn("candidate_promoted", eligible_events(state))
        self.assertNotIn("candidate_created", eligible_events(state))
        state = apply_event(state, controller_event(state, "candidate_promoted", refs=["artifact:candidate/C-007", "artifact:evaluation/CEVAL-007"]), artifacts)
        state = apply_event(state, controller_event(state, "signoff_started"), artifacts)
        self.assertIsNone(compute_terminal_status(state))
        self.assertIn("signoff_completed", eligible_events(state))
        self.assertNotIn("signoff_started", eligible_events(state))
        state = apply_event(state, controller_event(state, "signoff_completed", refs=["artifact:signoff/SO-007"]), artifacts)
        state = apply_event(state, controller_event(state, "terminal_certificate_emitted", refs=["artifact:terminal/TC-CLOSED"]), artifacts)
        self.assertEqual("CLOSED", state["closure_run"]["terminal_status"])

        exhausted = closure_state("SEARCHING")
        exhausted["closure_run"]["budget"].update({"candidate_evaluations_used": 1, "candidate_evaluations_limit": 1})
        exhausted["state_hash"] = canonical_hash(exhausted)
        self.assertEqual("BUDGET_EXHAUSTED", compute_terminal_status(exhausted))

    def test_source_drift_event_binds_the_new_revision_and_aborts_without_mutating_frozen_source(self) -> None:
        artifacts = artifact_map()
        state = closure_state("SEARCHING")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
        })
        state["state_hash"] = canonical_hash(state)
        terminal = drift_terminal()
        event = controller_event(state, "source_drift_detected", refs=["artifact:terminal/TC-DRIFT"])
        event["source_revision"] = terminal["source_revision"]
        pure = apply_event(state, event, {"artifact:terminal/TC-DRIFT": terminal})
        self.assertEqual("ABORTED_BY_SOURCE_DRIFT", pure["closure_run"]["terminal_status"])
        self.assertEqual("explicit-unversioned", pure["source"]["observed_revision"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, event_path, output_path = root / "state.json", root / "proposal.json", root / "state.next.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            event_path.write_text(json.dumps(event), encoding="utf-8")
            drift_artifacts = {**artifacts, "artifact:terminal/TC-DRIFT": terminal}
            write_artifact_graph(
                root,
                state,
                {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:terminal/TC-DRIFT"},
                drift_artifacts,
            )
            advanced = advance_once(state_path, event_path, root, output_path)
        self.assertEqual(pure, advanced)

    def test_contract_supersession_requires_a_strictly_new_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = closure_state("SEARCHING")
            current = artifact_map()
            state["closure_run"].update({
                "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": current["artifact:baseline/BL-001"]["content_hash"]},
                "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": current["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
                "active_candidate_refs": ["artifact:candidate/C-007"],
            })
            state["state_hash"] = canonical_hash(state)
            state_path = root / "state.0.json"
            event_path = root / "event.1.json"
            output_path = root / "state.1.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            stale_artifacts, refs = supersession_artifact_map(epoch=1)
            event = controller_event(state, "contract_superseded", refs=refs)
            event_path.write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(root, state, set(refs) | {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007"}, stale_artifacts)
            with self.assertRaises(ControllerConflict):
                advance_once(state_path, event_path, root, output_path)

            artifacts, refs = supersession_artifact_map(epoch=2)
            write_artifact_graph(root, state, set(refs) | {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007"}, artifacts)
            state2 = advance_once(state_path, event_path, root, output_path)
            self.assertEqual("BASELINING", state2["closure_run"]["phase"])
            self.assertEqual(2, state2["closure_run"]["contract_ref"]["epoch"])
            self.assertEqual(refs[0], state2["closure_run"]["handoff_ref"]["artifact_ref"])
            self.assertEqual(refs[2], state2["plan_ref"]["artifact_ref"])
            self.assertEqual([], state2["closure_run"]["active_candidate_refs"])

            historical = load_json(root / "contract" / "CC-001.json")
            historical["request"]["objective"] = "Self-consistent but altered historical contract."
            historical["content_hash"] = canonical_artifact_hash(historical)
            (root / "contract" / "CC-001.json").write_text(json.dumps(historical), encoding="utf-8")
            event2 = controller_event(state2, "baseline_qualified", refs=["artifact:baseline/BL-001"])
            (root / "event.2.json").write_text(json.dumps(event2), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(output_path, root / "event.2.json", root, root / "state.2.json")

    def test_controller_revalidates_the_writing_owned_frozen_contract(self) -> None:
        state = closure_state()
        artifacts = artifact_map()
        malformed = deepcopy(artifacts["artifact:contract/CC-001"])
        malformed.pop("contract_id")
        malformed["content_hash"] = canonical_artifact_hash(malformed)
        artifacts["artifact:contract/CC-001"] = malformed
        event = controller_event(state, "baseline_qualified", refs=["artifact:baseline/BL-001"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(root, state, {"artifact:contract/CC-001", "artifact:baseline/BL-001"}, artifacts)
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

    def test_bound_kernel_tampering_and_signoff_candidate_substitution_are_rejected(self) -> None:
        artifacts = artifact_map()

        def bind(state: dict, *, incumbent: bool = False) -> dict:
            state["closure_run"].update({
                "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
                "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
                "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
            })
            if incumbent:
                state["closure_run"]["incumbent_candidate_ref"] = "artifact:candidate/C-007"
            state["state_hash"] = canonical_hash(state)
            return state

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = bind(closure_state("SEARCHING"))
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            event = controller_event(state, "candidate_created", refs=["artifact:candidate/C-007"])
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(
                root,
                state,
                {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007"},
                artifacts,
            )
            verifier_path = root / "verifier" / "VB-001.json"
            tampered_verifier = load_json(verifier_path)
            tampered_verifier["qualification_summary"] = "tampered after binding"
            verifier_path.write_text(json.dumps(tampered_verifier), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = bind(closure_state("SIGNING_OFF"), incumbent=True)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            event = controller_event(state, "signoff_completed", refs=["artifact:signoff/SO-007"])
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(
                root,
                state,
                {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007"},
                artifacts,
            )
            substituted = deepcopy(artifacts["artifact:signoff/SO-007"])
            substituted["payload"]["candidate_hash"] = "sha256:" + "f" * 64
            substituted["content_hash"] = canonical_artifact_hash(substituted)
            write_artifact(root, "artifact:signoff/SO-007", substituted)
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

    def test_closed_terminal_requires_an_immutable_supporting_artifact_graph(self) -> None:
        artifacts = artifact_map()
        state = closure_state("SIGNING_OFF")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
            "incumbent_candidate_ref": "artifact:candidate/C-007",
            "signoff_result_ref": {"artifact_ref": "artifact:signoff/SO-007", "content_hash": artifacts["artifact:signoff/SO-007"]["content_hash"]},
        })
        state["closure_run"]["budget"].update({"candidate_evaluations_used": 1, "review_rounds_used": 1})
        state["state_hash"] = canonical_hash(state)
        event = controller_event(state, "terminal_certificate_emitted", refs=["artifact:terminal/TC-CLOSED"])
        canonical_refs = {
            ref for ref in artifacts
            if ref in {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007", "artifact:counterexample/CE-019", "artifact:signoff/SO-007", "artifact:terminal/TC-CLOSED"}
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            for ref in canonical_refs:
                write_artifact(root, ref, artifacts[ref])
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

            supporting = set().union(*(nested_artifact_refs(artifacts[ref]) for ref in canonical_refs)) - canonical_refs
            for ref in supporting:
                value = deepcopy(artifacts[ref]) if ref in artifacts else load_json(REVIEW_FIXTURE) if ref.startswith("artifact:review/") else generic_artifact(state, ref)
                write_artifact(root, ref, value)
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")
            for ref in supporting:
                if ref.startswith("artifact:review/"):
                    write_artifact(root, ref, review_artifact(state, artifacts["artifact:candidate/C-007"]))
            closed = advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")
            gate_path = root / "evidence" / "EV-GATE.json"
            tampered_gate = load_json(gate_path)
            tampered_gate["payload"]["summary"] = "tampered after CLOSED"
            gate_path.write_text(json.dumps(tampered_gate), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")
            write_artifact(root, "artifact:evidence/EV-GATE", generic_artifact(state, "artifact:evidence/EV-GATE"))
            review_path = root / "review" / "RR-REQ.json"
            tampered_review = load_json(review_path)
            tampered_review["summary"] = "Semantically valid text changed after sign-off."
            review_path.write_text(json.dumps(tampered_review), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")
        self.assertEqual("CLOSED", closed["closure_run"]["terminal_status"])

    def test_candidate_changed_refs_cannot_cross_allowed_or_protected_surfaces(self) -> None:
        artifacts = artifact_map()
        state = closure_state("SEARCHING")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
        })
        state["state_hash"] = canonical_hash(state)
        event = controller_event(state, "candidate_created", refs=["artifact:candidate/C-007"])
        event["payload"]["changed_refs"] = ["tests/protected/oracle.py"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(
                root,
                state,
                {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007"},
                artifacts,
            )
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

            event["payload"]["changed_refs"] = ["src/payments/charge.py"]
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            accepted = advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")
        self.assertEqual(["artifact:candidate/C-007"], accepted["closure_run"]["active_candidate_refs"])

    def test_promotion_rejects_an_evaluation_for_different_candidate_bytes(self) -> None:
        artifacts = artifact_map()
        state = closure_state("SEARCHING")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
            "active_candidate_refs": ["artifact:candidate/C-007"],
        })
        state["state_hash"] = canonical_hash(state)
        substituted = deepcopy(artifacts["artifact:evaluation/CEVAL-007"])
        substituted["payload"]["patch_hash"] = "sha256:" + "f" * 64
        substituted["content_hash"] = canonical_artifact_hash(substituted)
        artifacts["artifact:evaluation/CEVAL-SUBSTITUTED"] = substituted
        event = controller_event(
            state,
            "candidate_promoted",
            refs=["artifact:candidate/C-007", "artifact:evaluation/CEVAL-SUBSTITUTED"],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(
                root,
                state,
                set(event["payload"]["artifact_refs"]) | {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001"},
                artifacts,
            )
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

    def test_candidate_manifest_cannot_omit_verifier_kernel_protection(self) -> None:
        artifacts = artifact_map()
        state = closure_state("SEARCHING")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
        })
        state["state_hash"] = canonical_hash(state)
        candidate = deepcopy(artifacts["artifact:candidate/C-007"])
        candidate["payload"]["protected_paths"].remove("scripts/advance_closure.py")
        candidate["content_hash"] = canonical_artifact_hash(candidate)
        artifacts["artifact:candidate/C-007"] = candidate
        event = controller_event(state, "candidate_created", refs=["artifact:candidate/C-007"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(
                root,
                state,
                {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007"},
                artifacts,
            )
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

    def test_verifier_bundle_cannot_claim_unknown_contract_requirements(self) -> None:
        artifacts = artifact_map()
        state = closure_state("VERIFIER_QUALIFYING")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
        })
        state["state_hash"] = canonical_hash(state)
        verifier = deepcopy(artifacts["artifact:verifier/VB-001"])
        verifier["oracles"][0]["requirement_refs"] = ["VR-UNKNOWN"]
        verifier["content_hash"] = canonical_bundle_hash(verifier)
        artifacts["artifact:verifier/VB-001"] = verifier
        event = controller_event(state, "verifier_bundle_frozen", refs=["artifact:verifier/VB-001"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(
                root,
                state,
                {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001"},
                artifacts,
            )
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

    def test_replacement_incumbent_must_be_strictly_better_or_disprove_the_old_one(self) -> None:
        artifacts = trajectory_artifacts()
        state = closure_state("SEARCHING")
        state["closure_run"].update({
            "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": artifacts["artifact:contract/CC-001"]["content_hash"], "epoch": 1},
            "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": artifacts["artifact:baseline/BL-001"]["content_hash"]},
            "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": artifacts["artifact:verifier/VB-001"]["content_hash"], "epoch": 1},
            "incumbent_candidate_ref": "artifact:candidate/C-007",
            "active_candidate_refs": ["artifact:candidate/C-008"],
        })
        state["state_hash"] = canonical_hash(state)
        refs = ["artifact:candidate/C-008", "artifact:evaluation/CEVAL-008", "artifact:evaluation/CEVAL-007"]
        graph_refs = set(refs) | {"artifact:contract/CC-001", "artifact:baseline/BL-001", "artifact:verifier/VB-001", "artifact:candidate/C-007"}
        event = controller_event(state, "candidate_promoted", refs=refs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(root, state, graph_refs, artifacts)
            with self.assertRaises(ControllerConflict):
                advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")

            better = deepcopy(artifacts["artifact:evaluation/CEVAL-008"])
            better["payload"]["diff_stats"] = {"files_changed": 1, "lines_added": 1, "lines_deleted": 0}
            better["content_hash"] = canonical_artifact_hash(better)
            artifacts["artifact:evaluation/CEVAL-008"] = better
            write_artifact_graph(root, state, graph_refs, artifacts)
            promoted = advance_once(root / "state.json", root / "proposal.json", root, root / "state.next.json")
        self.assertEqual("artifact:candidate/C-008", promoted["closure_run"]["incumbent_candidate_ref"])

    def test_ranking_and_invalidation_are_lexicographic_and_global_when_kernel_changes(self) -> None:
        candidates = [
            {"candidate_id": "C-002", "hard_constraint_results": [], "regression_results": [], "soft_objective_metrics": [{"objective_ref": "SO-LATENCY", "value": 12.0, "direction": "minimize"}], "risk_findings": [], "diff_stats": {"files_changed": 2, "lines_added": 10, "lines_deleted": 2}, "evaluation_cost": {"wall_seconds": 2.0}, "eligible_for_promotion": True},
            {"candidate_id": "C-001", "hard_constraint_results": [], "regression_results": [], "soft_objective_metrics": [{"objective_ref": "SO-LATENCY", "value": 10.0, "direction": "minimize"}], "risk_findings": [], "diff_stats": {"files_changed": 3, "lines_added": 20, "lines_deleted": 1}, "evaluation_cost": {"wall_seconds": 4.0}, "eligible_for_promotion": True},
            {"candidate_id": "C-000", "hard_constraint_results": [], "regression_results": [], "soft_objective_metrics": [{"objective_ref": "SO-LATENCY", "value": 0.5, "direction": "minimize"}], "risk_findings": [], "diff_stats": {"files_changed": 1, "lines_added": 1, "lines_deleted": 0}, "evaluation_cost": {"wall_seconds": 1.0}, "eligible_for_promotion": False},
            {"candidate_id": "C-003", "hard_constraint_results": [{"id": "HC-001", "status": "fail"}], "regression_results": [], "soft_objective_metrics": [{"objective_ref": "SO-LATENCY", "value": 1.0, "direction": "minimize"}], "risk_findings": [], "diff_stats": {"files_changed": 1, "lines_added": 1, "lines_deleted": 0}, "evaluation_cost": {"wall_seconds": 1.0}, "eligible_for_promotion": False},
        ]
        contract = {"soft_objectives": [{"id": "SO-LATENCY", "priority": 1, "direction": "minimize"}]}
        ranked = rank_candidates(candidates, contract)
        self.assertEqual(["C-000", "C-001", "C-002", "C-003"], [item["candidate_id"] for item in ranked["ranked"]])
        self.assertEqual("C-000", ranked["winner_candidate_id"])
        self.assertTrue(ranked["ranked"][0]["controller_eligible"])
        self.assertEqual(
            {"hard_constraint_failure_count", "blocking_regression_count", "soft_objective_vector_by_priority", "unresolved_high_risk_count", "architecture_duplication_count", "changed_surface_risk", "diff_complexity", "changed_lines", "evaluation_cost", "controller_eligible"},
            set(ranked["ranked"][0]["comparison"]),
        )
        json.dumps(ranked, allow_nan=False)
        with self.assertRaises(ClosureError):
            rank_candidates([candidates[0], deepcopy(candidates[0])], contract)
        nonfinite = deepcopy(candidates[0])
        nonfinite["soft_objective_metrics"][0]["value"] = float("inf")
        with self.assertRaises(ClosureError):
            rank_candidates([nonfinite], contract)
        local = compute_invalidation({"kind": "counterexample", "ref": "CE-019"}, {"CE-019": ["C-002"], "C-002": ["SO-002"], "C-001": []})
        self.assertEqual(["C-002", "SO-002"], local["affected"])
        global_result = compute_invalidation({"kind": "verifier_bundle_hash", "ref": "VB-001"}, {"C-001": [], "C-002": []})
        self.assertTrue(global_result["new_epoch_required"])
        self.assertEqual("VERIFIER_QUALIFYING", global_result["restart_phase"])

    def test_advance_api_is_idempotent_conflict_safe_and_crash_replay_deterministic(self) -> None:
        artifacts = artifact_map()

        def prepare(root: Path) -> tuple[Path, Path, Path]:
            state = closure_state()
            event = controller_event(state, "baseline_qualified", refs=["artifact:baseline/BL-001"])
            state_path, event_path, output_path = root / "state.json", root / "proposal.json", root / "state.next.json"
            state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
            event_path.write_text(json.dumps(event, sort_keys=True), encoding="utf-8")
            write_artifact_graph(root, state, {"artifact:contract/CC-001", "artifact:baseline/BL-001"}, artifacts)
            return state_path, event_path, output_path

        with tempfile.TemporaryDirectory() as directory:
            direct_root = Path(directory) / "direct"
            direct_root.mkdir()
            state_path, event_path, output_path = prepare(direct_root)
            first = advance_once(state_path, event_path, direct_root, output_path)
            second = advance_once(state_path, event_path, direct_root, output_path)
            self.assertEqual(first, second)
            self.assertEqual(1, len((direct_root / "events.jsonl").read_text(encoding="utf-8").splitlines()))

            accepted_line = (direct_root / "events.jsonl").read_text(encoding="utf-8")
            altered_event = json.loads(accepted_line)
            altered_event["payload"]["summary"] = "tampered append-only history"
            (direct_root / "events.jsonl").write_text(json.dumps(altered_event) + "\n", encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(state_path, event_path, direct_root, output_path)
            (direct_root / "events.jsonl").write_text(accepted_line, encoding="utf-8")

            conflict = json.loads(event_path.read_text(encoding="utf-8"))
            conflict["payload"]["summary"] = "conflicting reuse"
            event_path.write_text(json.dumps(conflict, sort_keys=True), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(state_path, event_path, direct_root, output_path)

            crash_root = Path(directory) / "crash"
            crash_root.mkdir()
            crash_state, crash_event, crash_output = prepare(crash_root)
            with self.assertRaises(RuntimeError):
                advance_once(crash_state, crash_event, crash_root, crash_output, failpoint="after_event")
            recovered = advance_once(crash_state, crash_event, crash_root, crash_output)
            self.assertEqual(first["state_hash"], recovered["state_hash"])
            self.assertEqual(1, len((crash_root / "events.jsonl").read_text(encoding="utf-8").splitlines()))
            self.assertFalse((crash_root / ".advance-pending.json").exists())

    def test_transaction_recovery_rejects_symlink_changed_source_and_self_hashed_tampering(self) -> None:
        artifacts = artifact_map()

        def prepare(root: Path) -> tuple[Path, Path, Path]:
            state = closure_state()
            event = controller_event(state, "baseline_qualified", refs=["artifact:baseline/BL-001"])
            state_path, event_path, output_path = root / "state.json", root / "proposal.json", root / "state.next.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            event_path.write_text(json.dumps(event), encoding="utf-8")
            write_artifact_graph(root, state, {"artifact:contract/CC-001", "artifact:baseline/BL-001"}, artifacts)
            return state_path, event_path, output_path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            symlink_root = root / "symlink"
            symlink_root.mkdir()
            state_path, event_path, output_path = prepare(symlink_root)
            linked_state = symlink_root / "state.link.json"
            linked_state.symlink_to(state_path.name)
            with self.assertRaises(ControllerConflict):
                advance_once(linked_state, event_path, symlink_root, output_path)

            artifact_escape = root / "artifact-escape"
            artifact_escape.mkdir()
            write_artifact(artifact_escape, "artifact:contract/CC-001", artifacts["artifact:contract/CC-001"])
            escaped_root = root / "escaped-artifact"
            escaped_root.mkdir()
            escaped_state, escaped_event, escaped_output = prepare(escaped_root)
            (escaped_root / "contract" / "CC-001.json").unlink()
            (escaped_root / "contract").rmdir()
            (escaped_root / "contract").symlink_to(artifact_escape / "contract", target_is_directory=True)
            with self.assertRaises(ControllerConflict):
                advance_once(escaped_state, escaped_event, escaped_root, escaped_output)

            lock_root = root / "lock-symlink"
            lock_root.mkdir()
            lock_state, lock_event, lock_output = prepare(lock_root)
            outside_lock = root / "outside-lock.txt"
            outside_lock.write_text("must remain unchanged", encoding="utf-8")
            (lock_root / ".adapter.lock").symlink_to(outside_lock)
            with self.assertRaises(AdapterConflict):
                advance_once(lock_state, lock_event, lock_root, lock_output)
            self.assertEqual("must remain unchanged", outside_lock.read_text(encoding="utf-8"))

            changed_root = root / "changed"
            changed_root.mkdir()
            state_path, event_path, output_path = prepare(changed_root)
            with self.assertRaises(RuntimeError):
                advance_once(state_path, event_path, changed_root, output_path, failpoint="after_event")
            changed = load_json(state_path)
            changed["source"]["observed_revision"] = "changed-after-journal"
            changed["state_hash"] = canonical_hash(changed)
            state_path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(state_path, event_path, changed_root, output_path)

            forged_root = root / "forged-journal"
            forged_root.mkdir()
            state_path, event_path, output_path = prepare(forged_root)
            with self.assertRaises(RuntimeError):
                advance_once(state_path, event_path, forged_root, output_path, failpoint="after_journal")
            journal_path = forged_root / ".advance-pending.json"
            forged = load_json(journal_path)
            forged["next_state"]["closure_run"]["baseline_ref"]["content_hash"] = "sha256:" + "f" * 64
            forged["next_state"]["state_hash"] = canonical_hash(forged["next_state"])
            forged["next_state_hash"] = forged["next_state"]["state_hash"]
            journal_path.write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(state_path, event_path, forged_root, output_path)

            tampered_root = root / "tampered"
            tampered_root.mkdir()
            state_path, event_path, output_path = prepare(tampered_root)
            advance_once(state_path, event_path, tampered_root, output_path)
            tampered = load_json(output_path)
            tampered["closure_run"]["baseline_ref"]["content_hash"] = "sha256:" + "e" * 64
            tampered["state_hash"] = canonical_hash(tampered)
            self.assertEqual([], validate_state(tampered, STATE_SCHEMA))
            output_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(ControllerConflict):
                advance_once(state_path, event_path, tampered_root, output_path)

    def test_all_planned_synthetic_trajectories_replay_without_codex(self) -> None:
        fixture = load_json(TRAJECTORY_FIXTURE)
        self.assertEqual(fixture["direct"]["expected_decision"], admit(fixture["direct"]["facts"])["decision"])
        self.assertGreaterEqual(len(fixture["closure"]), 6)
        artifacts = trajectory_artifacts()

        for trajectory in fixture["closure"]:
            with self.subTest(trajectory=trajectory["id"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = closure_state()
                state_path = root / "state.0.json"
                state_path.write_text(json.dumps(state), encoding="utf-8")
                write_artifact_graph(root, state, {"artifact:contract/CC-001"}, artifacts)
                accepted_count = 0
                for index, step in enumerate(trajectory["steps"], 1):
                    fields = {"budget_delta": step["budget_delta"]} if "budget_delta" in step else {}
                    event = controller_event(state, step["type"], refs=step.get("refs", []), **fields)
                    if "changed_refs" in step:
                        event["payload"]["changed_refs"] = step["changed_refs"]
                    if "source_revision" in step:
                        event["source_revision"] = step["source_revision"]
                    event_path = root / f"proposal.{index}.json"
                    output_path = root / f"state.{index}.json"
                    event_path.write_text(json.dumps(event), encoding="utf-8")
                    if step.get("refs"):
                        write_artifact_graph(root, state, set(step["refs"]), artifacts)
                    if step.get("expect") == "rejected":
                        with self.assertRaises(ControllerConflict):
                            advance_once(state_path, event_path, root, output_path)
                        self.assertFalse(output_path.exists())
                        continue
                    previous_version = state["state_version"]
                    state = advance_once(state_path, event_path, root, output_path)
                    accepted_count += 1
                    self.assertEqual(previous_version + 1, state["state_version"])
                    self.assertEqual(state["state_hash"], canonical_hash(state))
                    self.assertEqual([], validate_state(state, STATE_SCHEMA), step["type"])
                    state_path = output_path
                self.assertEqual("TERMINAL", state["closure_run"]["phase"])
                self.assertEqual(trajectory["expected_terminal"], state["closure_run"]["terminal_status"])
                accepted_events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(accepted_count, len(accepted_events))
                self.assertTrue(all(isinstance(item["payload"].get("artifact_bindings"), list) for item in accepted_events))
                previous_hash = GENESIS_EVENT_HASH
                for accepted in accepted_events:
                    self.assertEqual(previous_hash, accepted["previous_event_hash"])
                    self.assertEqual(_accepted_event_hash(accepted), accepted["event_hash"])
                    previous_hash = accepted["event_hash"]

    def test_controller_errors_use_the_planned_stable_vocabulary(self) -> None:
        self.assertEqual("E_SOURCE_DRIFT", _error_code(ControllerConflict("proposal source revision differs from workflow source")))
        self.assertEqual("E_PROTECTED_SURFACE_CHANGED", _error_code(ControllerConflict("changed ref crosses protected surface")))
        self.assertEqual("E_HASH_MISMATCH", _error_code(ControllerConflict("content hash mismatch")))
        self.assertNotIn("E_CONTROLLER_CONFLICT", {_error_code(ControllerConflict("actor cannot accept promotion"))})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = closure_state()
            event = controller_event(state, "baseline_qualified", refs=["artifact:baseline/BL-001"], actor="worker")
            (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
            (root / "proposal.json").write_text(json.dumps(event), encoding="utf-8")
            artifacts = artifact_map()
            write_artifact_graph(root, state, {"artifact:contract/CC-001", "artifact:baseline/BL-001"}, artifacts)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "advance_closure.py"), "--state", str(root / "state.json"), "--event", str(root / "proposal.json"), "--artifacts-root", str(root), "--output", str(root / "state.next.json")],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(2, result.returncode)
        self.assertEqual("E_UNAUTHORIZED_TRANSITION", json.loads(result.stdout)["error"]["code"])

    def test_public_advance_cli_matches_the_planned_command_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = closure_state()
            event = controller_event(state, "baseline_qualified", refs=["artifact:baseline/BL-001"])
            state_path, event_path, output_path = root / "state.json", root / "proposal.json", root / "state.next.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            event_path.write_text(json.dumps(event), encoding="utf-8")
            artifacts = artifact_map()
            write_artifact_graph(root, state, {"artifact:contract/CC-001", "artifact:baseline/BL-001"}, artifacts)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "advance_closure.py"), "--state", str(state_path), "--event", str(event_path), "--artifacts-root", str(root), "--output", str(output_path)],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
