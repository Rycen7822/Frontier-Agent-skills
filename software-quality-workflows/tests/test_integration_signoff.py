from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _workflow_state import canonical_artifact_hash, load_json  # noqa: E402
from advance_closure import _validate_generic_artifact  # noqa: E402
from local_workflow_adapter import AdapterConflict  # noqa: E402
from reconcile_workflow import reconcile  # noqa: E402
from test_candidate_task_records import (  # noqa: E402
    _manifest,
    _repository,
    _result,
    _search_adapter,
    _session,
    _task,
    _write_session_outputs,
)


REVIEW_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "valid-review-result.json"
ARTIFACT_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "valid-artifacts.json"


def _candidate_chain(directory: Path):
    repo, revision = _repository(directory)
    adapter = _search_adapter(repo, revision)
    adapter.create_candidate_worktree(
        repo, candidate_id="CAND-0007", base_revision=revision, writer_id="worker-01",
        allowed_write_paths=["src/payments/**", "tests/payments/**"],
        protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
    )
    task = _task(adapter, revision)
    adapter.prepare_codex_task(task)
    session = _session(task)
    result = _result(task)
    _write_session_outputs(adapter, session, result)
    adapter.record_codex_session(task["task_id"], session)
    worktree = Path(task["working_directory"])
    (worktree / "src" / "payments" / "charge.py").write_text("def charge():\n    return 'new'\n", encoding="utf-8")
    snapshot = adapter.inspect_candidate_snapshot(
        repo, candidate_id="CAND-0007", expected_base_revision=revision,
        allowed_write_paths=task["allowed_write_paths"], protected_paths=task["protected_paths"],
    )
    manifest = _manifest(adapter, task, snapshot)
    adapter.record_codex_result(repo, result, candidate_manifest=manifest)
    archive = adapter.archive_candidate(
        repo, candidate_id="CAND-0007", expected_base_revision=revision,
        expected_snapshot_hash=snapshot["snapshot_hash"], allowed_write_paths=task["allowed_write_paths"],
        protected_paths=task["protected_paths"],
    )
    return repo, revision, adapter, task, manifest, snapshot, archive


def _review(candidate: dict, scope_manifest: dict) -> dict:
    review = load_json(REVIEW_FIXTURE)
    review.update({
        "reviewed_base_sha": candidate["payload"]["base_candidate_hash"],
        "reviewed_head_sha": candidate["payload"]["patch_hash"],
        "reviewed_scope_hash": scope_manifest["scope_hash"],
        "coverage": [
            {"path": item["path"], "status": "full", "snapshot_id": item["snapshot_id"]}
            for item in scope_manifest["paths"]
        ],
    })
    return review


def _axis_evidence(adapter, integration: dict) -> dict[str, dict]:
    state = adapter.load_state()
    values = {
        "artifact:evidence/EV-VERIFIER": {
            "axis": "verifier_integrity", "verdict": "pass",
            "verifier_bundle_hash": state["closure_run"]["verifier_bundle_ref"]["content_hash"],
            "integration_ref": integration["integration_ref"],
        },
        "artifact:evidence/EV-AUTHORITY": {
            "axis": "authority", "verdict": "pass", "publication_ceiling": "local_patch",
            "external_writes": False, "integration_ref": integration["integration_ref"],
        },
    }
    result = {}
    for ref, payload in values.items():
        artifact_id = ref.rsplit("/", 1)[-1]
        artifact = {
            "schema_id": "sqw://artifact-envelope/1.0", "artifact_id": artifact_id,
            "workflow_id": state["workflow_id"], "source_revision": state["source"]["observed_revision"],
            "scope_hash": state["source"]["scope_hash"], "created_at": "2026-07-14T15:00:00+08:00",
            "producer": {"actor": "controller", "run_id": "RUN-signoff"}, "classification": "internal",
            "mime_type": "application/json", "command_ref": "controller:four-axis-signoff",
            "redaction_policy": "none_required", "content_hash": "sha256:" + "0" * 64, "payload": payload,
        }
        artifact["content_hash"] = canonical_artifact_hash(artifact)
        result[ref] = artifact
    return result


def _signoff(adapter, candidate: dict, integration: dict, reviews: dict[str, dict], evidence: dict[str, dict]) -> dict:
    signoff = next(
        item for item in load_json(ARTIFACT_FIXTURE)
        if item["schema_id"] == "sqw://closure-artifacts/signoff-result/1.0"
    )
    state = adapter.load_state()
    run = state["closure_run"]
    requirements_ref = "artifact:review/RR-REQ"
    engineering_ref = "artifact:review/RR-ENG"
    integration_ref = integration["integration_ref"]
    signoff.update({
        "artifact_id": "SO-0007",
        "workflow_id": state["workflow_id"],
        "closure_epoch": run["contract_ref"]["epoch"],
        "source_revision": state["source"]["observed_revision"],
        "scope_hash": state["source"]["scope_hash"],
        "contract_hash": run["contract_ref"]["content_hash"],
        "verifier_bundle_hash": run["verifier_bundle_ref"]["content_hash"],
        "producer": {"actor": "controller", "run_id": "RUN-signoff"},
    })
    signoff["payload"].update({
        "candidate_ref": "artifact:candidate/C-0007",
        "candidate_hash": candidate["content_hash"],
        "axes": {
            "requirements": {"status": "pass", "review_result_ref": requirements_ref, "review_result_hash": canonical_artifact_hash(reviews[requirements_ref])},
            "engineering": {"status": "pass", "review_result_ref": engineering_ref, "review_result_hash": canonical_artifact_hash(reviews[engineering_ref])},
            "verifier_integrity": {"status": "pass", "evidence_refs": ["artifact:evidence/EV-VERIFIER"]},
            "authority": {"status": "pass", "evidence_refs": ["artifact:evidence/EV-AUTHORITY"]},
        },
        "required_gate_results": [{"gate_id": "integration-reverification", "status": "pass", "evidence_refs": [integration_ref]}],
        "freshness": {
            "source_revision": state["source"]["observed_revision"],
            "scope_hash": state["source"]["scope_hash"],
            "contract_hash": run["contract_ref"]["content_hash"],
            "verifier_bundle_hash": run["verifier_bundle_ref"]["content_hash"],
            "baseline_hash": run["baseline_ref"]["content_hash"],
        },
        "residual_risk": [],
        "verdict": "pass",
    })
    signoff["content_hash"] = canonical_artifact_hash(signoff)
    return signoff


class IntegrationSignoffTests(unittest.TestCase):
    def test_archived_candidate_replays_identically_in_two_clean_integration_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision, adapter, task, _manifest_value, snapshot, archive = _candidate_chain(Path(directory))
            observed: list[dict] = []
            for integration_id in ("INTEGRATION-0001", "INTEGRATION-0002"):
                adapter.create_integration_worktree(
                    repo, integration_id=integration_id, base_revision=revision,
                    allowed_write_paths=task["allowed_write_paths"], protected_paths=task["protected_paths"],
                )
                pending = reconcile(adapter.load_state(), workflow_root=adapter.root, verify_artifacts=False)
                self.assertIn("integration_incomplete", {item["kind"] for item in pending["issues"]})
                applied = adapter.apply_candidate_to_integration(
                    repo, candidate_id="CAND-0007", integration_id=integration_id,
                    expected_candidate_snapshot_hash=snapshot["snapshot_hash"],
                    archive_artifact=archive["archive_artifact"],
                )
                reconciled = reconcile(adapter.load_state(), workflow_root=adapter.root, verify_artifacts=False)
                self.assertNotIn("integration_incomplete", {item["kind"] for item in reconciled["issues"]})
                observed.append(applied)
                integration = Path(applied["worktree_path"])
                self.assertIn("return 'new'", (integration / "src" / "payments" / "charge.py").read_text(encoding="utf-8"))
                self.assertEqual("HIDDEN = True\n", (integration / "tests" / "holdout" / "secret_case.py").read_text(encoding="utf-8"))
            self.assertEqual(observed[0]["snapshot"]["patch_hash"], observed[1]["snapshot"]["patch_hash"])
            self.assertEqual(observed[0]["snapshot"]["tree_hash"], observed[1]["snapshot"]["tree_hash"])
            self.assertEqual(snapshot["tree_hash"], observed[0]["snapshot"]["tree_hash"])
            self.assertTrue(Path(task["working_directory"]).is_dir(), "candidate worktree must not be promoted in place")

    def test_four_axis_signoff_requires_fresh_integration_scope_and_review_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision, adapter, task, manifest, snapshot, archive = _candidate_chain(Path(directory))
            adapter.create_integration_worktree(
                repo, integration_id="INTEGRATION-0001", base_revision=revision,
                allowed_write_paths=task["allowed_write_paths"], protected_paths=task["protected_paths"],
            )
            integration = adapter.apply_candidate_to_integration(
                repo, candidate_id="CAND-0007", integration_id="INTEGRATION-0001",
                expected_candidate_snapshot_hash=snapshot["snapshot_hash"], archive_artifact=archive["archive_artifact"],
            )
            reviews = {
                "artifact:review/RR-REQ": _review(manifest, integration["scope_manifest"]),
                "artifact:review/RR-ENG": _review(manifest, integration["scope_manifest"]),
            }
            evidence = _axis_evidence(adapter, integration)
            signoff = _signoff(adapter, manifest, integration, reviews, evidence)
            stale_reviews = deepcopy(reviews)
            stale_reviews["artifact:review/RR-REQ"]["coverage"][0]["snapshot_id"] = "sha256:" + "f" * 64
            with self.assertRaises(AdapterConflict):
                adapter.record_integration_signoff(repo, signoff, candidate_manifest=manifest, integration=integration, review_results=stale_reviews, evidence_artifacts=evidence)
            integration_path = Path(integration["worktree_path"])
            changed = integration_path / "src" / "payments" / "charge.py"
            changed.write_text("def charge():\n    return 'drifted'\n", encoding="utf-8")
            with self.assertRaises(AdapterConflict):
                adapter.record_integration_signoff(repo, signoff, candidate_manifest=manifest, integration=integration, review_results=reviews, evidence_artifacts=evidence)
            changed.write_text("def charge():\n    return 'new'\n", encoding="utf-8")
            recorded = adapter.record_integration_signoff(repo, signoff, candidate_manifest=manifest, integration=integration, review_results=reviews, evidence_artifacts=evidence)
            self.assertEqual("signoff_completed", recorded["event_proposal"]["type"])
            self.assertTrue((adapter.root / "signoff" / "SO-0007.json").is_file())
            self.assertTrue((adapter.root / "review" / "RR-REQ.json").is_file())
            self.assertEqual("pass", recorded["signoff"]["payload"]["verdict"])
            for ref in [integration["integration_ref"], *evidence]:
                kind, name = ref.removeprefix("artifact:").split("/", 1)
                artifact = load_json(adapter.root / kind / f"{name}.json")
                self.assertEqual([], _validate_generic_artifact(ref, artifact, adapter.load_state()))


if __name__ == "__main__":
    unittest.main()
