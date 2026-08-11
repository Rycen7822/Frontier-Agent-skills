from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

import jsonschema


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = SKILL_ROOT / "schemas"
DIGEST = "sha256:" + "a" * 64


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def review_result() -> dict:
    return {
        "schema_version": "4.0",
        "code_review_verdict": "pass",
        "verification_status": "passed",
        "spec_traceability": {"status": "not_applicable", "evidence_refs": []},
        "coverage": [{"path": "src/owner.py", "status": "full", "snapshot_id": "snapshot-1"}],
        "blocking_reasons": [],
        "reviewed_base_revision": "base-revision",
        "reviewed_head_revision": "head-revision",
        "reviewed_paths": ["src/owner.py"],
        "findings": [],
    }


def publication_readiness() -> dict:
    return {
        "schema_version": "2.0",
        "review_result_ref": "artifact:review/local-review",
        "review_result_digest": DIGEST,
        "source_revision": "head-revision",
        "requested_action": "branch_push",
        "publication_ceiling": {
            "allowed_actions": ["branch_push"],
            "authority_ref": "authority:user-request",
        },
        "remote_checks": [],
        "required_approvals": [],
        "branch_policy": {"status": "not_applicable", "evidence_ref": "policy:none"},
        "readiness": "ready",
        "blocking_reasons": [],
    }


class QuickIdentityContractTests(unittest.TestCase):
    def test_active_schemas_are_valid(self) -> None:
        for name in ("review-result.schema.json", "publication-readiness.schema.json"):
            jsonschema.Draft202012Validator.check_schema(load_schema(name))

    def test_review_uses_explicit_revisions_and_paths(self) -> None:
        validator = jsonschema.Draft202012Validator(load_schema("review-result.schema.json"))
        value = review_result()
        validator.validate(value)
        self.assertEqual(value["reviewed_paths"], [item["path"] for item in value["coverage"]])
        for retired in ("reviewed_base_sha", "reviewed_head_sha", "reviewed_scope_hash"):
            invalid = deepcopy(value)
            invalid[retired] = DIGEST
            with self.subTest(retired=retired), self.assertRaises(jsonschema.ValidationError):
                validator.validate(invalid)

    def test_publication_has_one_review_boundary_digest(self) -> None:
        validator = jsonschema.Draft202012Validator(load_schema("publication-readiness.schema.json"))
        value = publication_readiness()
        validator.validate(value)
        digest_fields = [key for key in value if key.endswith(("_digest", "_hash"))]
        self.assertEqual(["review_result_digest"], digest_fields)
        for retired in ("review_result_hash", "scope_hash"):
            invalid = deepcopy(value)
            invalid[retired] = DIGEST
            with self.subTest(retired=retired), self.assertRaises(jsonschema.ValidationError):
                validator.validate(invalid)

    def test_orphan_verifier_bundle_is_removed(self) -> None:
        self.assertFalse((SCHEMA_ROOT / "verifier-bundle.schema.json").exists())


if __name__ == "__main__":
    unittest.main()
