from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import (  # noqa: E402
    canonical_artifact_hash,
    load_json,
    validate_closure_artifact,
    validate_publication_readiness,
    validate_review_result,
)


ARTIFACT_SCHEMA = load_json(ROOT / "schemas" / "closure-artifacts.schema.json")
REVIEW_SCHEMA = load_json(ROOT / "schemas" / "review-result.schema.json")
PUBLICATION_SCHEMA = load_json(ROOT / "schemas" / "publication-readiness.schema.json")
ARTIFACT_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "valid-artifacts.json"
REVIEW_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "valid-review-result.json"
PUBLICATION_FIXTURE = ROOT / "tests" / "fixtures" / "closure" / "valid-publication-readiness.json"


def artifacts() -> list[dict]:
    values = load_json(ARTIFACT_FIXTURE)
    for value in values:
        value["content_hash"] = canonical_artifact_hash(value)
    return values


def review_manifest() -> dict:
    return {
        "base_revision": "base-001",
        "head_revision": "head-001",
        "scope_hash": "sha256:" + "b" * 64,
        "paths": [{"path": "src/payments/charge.py", "snapshot_id": "sha256:" + "a" * 64}],
    }


class ClosureArtifactTests(unittest.TestCase):
    def test_local_review_and_publication_schemas_have_disjoint_authority(self) -> None:
        review_fields = set(REVIEW_SCHEMA["properties"])
        publication_fields = set(PUBLICATION_SCHEMA["properties"])
        self.assertFalse({"merge_readiness", "external_approvals", "requested_action", "publication_ceiling"} & review_fields)
        self.assertTrue({"requested_action", "publication_ceiling", "remote_checks", "required_approvals", "branch_policy", "readiness"} <= publication_fields)
        self.assertTrue((ROOT / "operator" / "review" / "result-consistency.md").is_file())
        self.assertTrue((ROOT / "operator" / "review" / "publication-readiness.md").is_file())

    def test_tagged_union_accepts_exactly_the_eight_planned_artifact_types(self) -> None:
        expected = {
            "admission-result", "baseline-result", "candidate-manifest", "candidate-evaluation",
            "counterexample", "signoff-result", "terminal-certificate", "plan-change-proposal",
        }
        values = artifacts()
        observed = {value["schema_id"].split("/")[-2] for value in values}
        self.assertEqual(expected, observed)
        for value in values:
            with self.subTest(schema_id=value["schema_id"]):
                self.assertEqual([], validate_closure_artifact(value, ARTIFACT_SCHEMA))

    def test_union_rejects_unknown_fields_wrong_tag_hash_and_identity_drift(self) -> None:
        value = artifacts()[3]
        value["unexpected"] = True
        self.assertIn("artifact.schema", {item.code for item in validate_closure_artifact(value, ARTIFACT_SCHEMA)})
        value = artifacts()[3]
        value["schema_id"] = "sqw://closure-artifacts/counterexample/1.0"
        value["content_hash"] = canonical_artifact_hash(value)
        self.assertIn("artifact.schema", {item.code for item in validate_closure_artifact(value, ARTIFACT_SCHEMA)})
        value = artifacts()[3]
        value["payload"]["eligible_for_promotion"] = False
        self.assertIn("artifact.hash", {item.code for item in validate_closure_artifact(value, ARTIFACT_SCHEMA)})
        value = artifacts()[3]
        self.assertIn(
            "artifact.identity",
            {item.code for item in validate_closure_artifact(value, ARTIFACT_SCHEMA, expected_contract_hash="sha256:" + "f" * 64)},
        )

    def test_baseline_precedes_and_cannot_claim_a_future_verifier_bundle(self) -> None:
        baseline = artifacts()[1]
        self.assertEqual("not_frozen", baseline["verifier_bundle_hash"])
        self.assertEqual([], validate_closure_artifact(baseline, ARTIFACT_SCHEMA))
        baseline["verifier_bundle_hash"] = "sha256:" + "2" * 64
        baseline["content_hash"] = canonical_artifact_hash(baseline)
        self.assertIn("artifact.schema", {item.code for item in validate_closure_artifact(baseline, ARTIFACT_SCHEMA)})

    def test_candidate_signoff_and_terminal_semantics_fail_closed(self) -> None:
        manifest = artifacts()[2]
        manifest["payload"]["protected_paths"] = ["src/payments/**"]
        manifest["content_hash"] = canonical_artifact_hash(manifest)
        self.assertIn("artifact.scope", {item.code for item in validate_closure_artifact(manifest, ARTIFACT_SCHEMA)})

        signoff = artifacts()[5]
        signoff["payload"]["axes"]["authority"]["status"] = "fail"
        signoff["content_hash"] = canonical_artifact_hash(signoff)
        self.assertIn("artifact.signoff", {item.code for item in validate_closure_artifact(signoff, ARTIFACT_SCHEMA)})

        terminal = artifacts()[6]
        terminal["payload"]["minimal_missing_information"] = []
        terminal["content_hash"] = canonical_artifact_hash(terminal)
        self.assertIn("artifact.terminal", {item.code for item in validate_closure_artifact(terminal, ARTIFACT_SCHEMA)})

    def test_nested_evaluation_terminal_and_timestamp_edges_fail_closed(self) -> None:
        evaluation = artifacts()[3]
        evaluation["payload"]["hard_constraint_results"] = [{"id": "HC-001", "status": "fail", "evidence_refs": ["artifact:evidence/EV-FAIL"]}]
        evaluation["content_hash"] = canonical_artifact_hash(evaluation)
        self.assertIn("artifact.evaluation", {item.code for item in validate_closure_artifact(evaluation, ARTIFACT_SCHEMA)})

        signoff = artifacts()[5]
        signoff["payload"]["verdict"] = "fail"
        signoff["content_hash"] = canonical_artifact_hash(signoff)
        self.assertIn("artifact.signoff", {item.code for item in validate_closure_artifact(signoff, ARTIFACT_SCHEMA)})

        terminal = artifacts()[6]
        terminal["payload"]["terminal_status"] = "AUTHORITY_BLOCKED"
        terminal["payload"]["blocking_items"] = []
        terminal["payload"]["evidence_refs"] = []
        terminal["content_hash"] = canonical_artifact_hash(terminal)
        self.assertIn("artifact.terminal", {item.code for item in validate_closure_artifact(terminal, ARTIFACT_SCHEMA)})

        naive = artifacts()[3]
        naive["created_at"] = "2026-07-14T12:03:00"
        naive["content_hash"] = canonical_artifact_hash(naive)
        self.assertIn("artifact.schema", {item.code for item in validate_closure_artifact(naive, ARTIFACT_SCHEMA)})

    def test_risk_findings_have_a_machine_countable_category(self) -> None:
        evaluation = artifacts()[3]
        evaluation["payload"]["risk_findings"] = [{
            "id": "RISK-ARCH-001",
            "severity": "medium",
            "blocking": False,
            "category": "architecture_duplication",
            "summary": "A second transition owner was introduced.",
            "evidence_refs": ["artifact:evidence/EV-ARCH"],
        }]
        evaluation["content_hash"] = canonical_artifact_hash(evaluation)
        self.assertEqual([], validate_closure_artifact(evaluation, ARTIFACT_SCHEMA))
        del evaluation["payload"]["risk_findings"][0]["category"]
        evaluation["content_hash"] = canonical_artifact_hash(evaluation)
        self.assertIn("artifact.schema", {item.code for item in validate_closure_artifact(evaluation, ARTIFACT_SCHEMA)})

    def test_review_schema_and_manifest_semantics_bind_scope_freshness_and_readiness(self) -> None:
        result = load_json(REVIEW_FIXTURE)
        manifest = review_manifest()
        self.assertEqual([], validate_review_result(result, REVIEW_SCHEMA, manifest, current_head="head-001", current_scope_hash="sha256:" + "b" * 64))

        sampled = deepcopy(result)
        sampled["coverage"][0]["status"] = "sampled"
        sampled["coverage"][0]["sampling_note"] = "Reviewed the changed parser and its owning call path."
        self.assertEqual([], validate_review_result(sampled, REVIEW_SCHEMA, manifest, current_head="head-001", current_scope_hash="sha256:" + "b" * 64))

        mixed = deepcopy(result)
        mixed["merge_readiness"] = "ready"
        mixed["external_approvals"] = "satisfied"
        self.assertIn("review.schema", {item.code for item in validate_review_result(mixed, REVIEW_SCHEMA, manifest, current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})

        stale = deepcopy(result)
        self.assertIn("review.freshness", {item.code for item in validate_review_result(stale, REVIEW_SCHEMA, manifest, current_head="head-002", current_scope_hash="sha256:" + "b" * 64)})
        snapshot = deepcopy(result)
        snapshot["coverage"][0]["snapshot_id"] = "sha256:" + "c" * 64
        self.assertIn("review.manifest", {item.code for item in validate_review_result(snapshot, REVIEW_SCHEMA, manifest, current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})
        blocking = deepcopy(result)
        blocking["findings"] = [{
            "id": "F-001", "severity": "medium", "blocking": True, "category": "correctness",
            "path": "src/payments/charge.py", "line": 10, "evidence": "The race remains.",
            "impact": "Duplicate charge.", "recommended_fix": "Serialize ownership.", "confidence": "high",
            "verification": "Focused oracle failed.", "code_fixable": True, "source_revision": "head-001",
        }]
        blocking["blocking_reasons"] = ["F-001"]
        self.assertIn("review.consistency", {item.code for item in validate_review_result(blocking, REVIEW_SCHEMA, manifest, current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})
        duplicate_manifest = review_manifest()
        duplicate_manifest["paths"].append(deepcopy(duplicate_manifest["paths"][0]))
        self.assertIn("review.manifest", {item.code for item in validate_review_result(result, REVIEW_SCHEMA, duplicate_manifest, current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})

    def test_publication_readiness_is_separate_and_cannot_infer_remote_readiness(self) -> None:
        review = load_json(REVIEW_FIXTURE)
        publication = load_json(PUBLICATION_FIXTURE)
        publication["review_result_hash"] = canonical_artifact_hash(review)
        self.assertEqual([], validate_publication_readiness(publication, PUBLICATION_SCHEMA, review, REVIEW_SCHEMA, review_manifest(), current_head="head-001", current_scope_hash="sha256:" + "b" * 64))

        sampled_review = deepcopy(review)
        sampled_review["coverage"][0]["status"] = "sampled"
        sampled_review["coverage"][0]["sampling_note"] = "Only the changed path was sampled."
        publication["review_result_hash"] = canonical_artifact_hash(sampled_review)
        self.assertIn("publication.consistency", {item.code for item in validate_publication_readiness(publication, PUBLICATION_SCHEMA, sampled_review, REVIEW_SCHEMA, review_manifest(), current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})

        unauthorized = deepcopy(publication)
        unauthorized["review_result_hash"] = canonical_artifact_hash(review)
        unauthorized["publication_ceiling"]["allowed_actions"] = ["branch_push"]
        self.assertIn("publication.authority", {item.code for item in validate_publication_readiness(unauthorized, PUBLICATION_SCHEMA, review, REVIEW_SCHEMA, review_manifest(), current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})

        failed_remote = deepcopy(publication)
        failed_remote["review_result_hash"] = canonical_artifact_hash(review)
        failed_remote["remote_checks"][0]["status"] = "failed"
        self.assertIn("publication.consistency", {item.code for item in validate_publication_readiness(failed_remote, PUBLICATION_SCHEMA, review, REVIEW_SCHEMA, review_manifest(), current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})

        unexplained = deepcopy(publication)
        unexplained["review_result_hash"] = canonical_artifact_hash(review)
        unexplained["readiness"] = "blocked"
        self.assertIn("publication.schema", {item.code for item in validate_publication_readiness(unexplained, PUBLICATION_SCHEMA, review, REVIEW_SCHEMA, review_manifest(), current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})

        unvalidated_review = deepcopy(review)
        unvalidated_review["schema_version"] = "2.0"
        publication["review_result_hash"] = canonical_artifact_hash(unvalidated_review)
        self.assertIn("publication.review", {item.code for item in validate_publication_readiness(publication, PUBLICATION_SCHEMA, unvalidated_review, REVIEW_SCHEMA, review_manifest(), current_head="head-001", current_scope_hash="sha256:" + "b" * 64)})


if __name__ == "__main__":
    unittest.main()
