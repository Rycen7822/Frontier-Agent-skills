from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _model_evolution_apparatus import (  # noqa: E402
    derive_retry_budget,
    audit_plan_transport,
    materialized_attempt_policy,
    project_transport_sequence,
    validate_apparatus_retry_policy,
    validate_outcome_free_incomplete_command,
)
from _model_evolution_campaign import (  # noqa: E402
    qualification_request_ceilings,
    require_qualification_request_ceilings,
)
from _model_evolution_contract import (  # noqa: E402
    ContractError,
    canonical_bytes,
    content_hash,
    validate_document,
)
from _model_evolution_materialization import (  # noqa: E402
    _campaign_runner_attempt_policy,
)


POLICY_PATH = (
    ROOT
    / "evaluation/model-evolution/confirmatory-v2/apparatus-retry-policy-v1.json"
)
INDEX_PATH = (
    ROOT / "evaluation/model-evolution/confirmatory-v1/sentinel-index-v3.json"
)


def host_result(ordinal: int, attempt: int) -> dict[str, object]:
    return {
        "record_type": "skill-evaluator-host-result/2",
        "envelope": {
            "attempt": attempt,
            "entry_id": f"entry.test-{ordinal}",
            "entry_ordinal": ordinal,
            "request_id": f"request.{ordinal}.{attempt}.execute_case",
            "request_kind": "execute_case",
        },
        "terminal": True,
        "terminal_status": "protocol_error",
        "protocol_error": {
            "kind": "malformed_record",
            "message": (
                "Codex stream has incomplete items: stdout record 9 "
                "(item.started/command_execution)"
            ),
        },
        "timeout": False,
        "refusal": False,
        "treatment_error": None,
        "usage": {"records": []},
        "context": {"bytes": 0},
        "cleanup": {"status": "clean"},
        "actions": [],
        "artifacts": [],
        "assertions": [],
        "handoffs": [],
        "principals": [],
        "state": [],
    }


def failed(ordinal: int, attempt: int) -> dict[str, object]:
    return {
        "entry_ordinal": ordinal,
        "attempt": attempt,
        "request_id": f"request.{ordinal}.{attempt}.execute_case",
        "valid": False,
        "host_result": host_result(ordinal, attempt),
    }


def valid(ordinal: int, attempt: int) -> dict[str, object]:
    return {
        "entry_ordinal": ordinal,
        "attempt": attempt,
        "request_id": f"request.{ordinal}.{attempt}.execute_case",
        "valid": True,
    }


class ApparatusRetryContract(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_observed_rate_derives_limits_and_exact_budget(self) -> None:
        validate_apparatus_retry_policy(self.policy)
        derived = derive_retry_budget(
            valid_statistical_samples=876,
            observed_failures=7,
            observed_transport_attempts=93,
            confidence_level=0.95,
            campaign_exhaustion_tail=0.05,
            calibration_attempts=128,
            probe_attempt_ceiling=12,
        )
        self.assertEqual(5, derived["max_attempts_per_entry"])
        self.assertEqual(156, derived["campaign_apparatus_reserve"])
        self.assertEqual(1032, derived["execute_request_ceiling"])
        self.assertEqual(1160, derived["model_grade_request_ceiling"])
        self.assertEqual(2204, derived["provider_request_ceiling"])

        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        ceilings = qualification_request_ceilings(
            index,
            repository_root=ROOT,
            campaign_root=ROOT,
            probe_count=6,
            apparatus_policy=self.policy,
        )
        expected = {"provider_requests": 2204, "execute": 1032, "model_grade": 1160}
        require_qualification_request_ceilings(expected, ceilings)
        for field in expected:
            for delta in (-1, 1):
                changed = dict(expected)
                changed[field] += delta
                with self.assertRaises(ContractError):
                    require_qualification_request_ceilings(changed, ceilings)

    def test_two_incomplete_commands_then_success_preserves_sample_prefix(self) -> None:
        projection = project_transport_sequence(
            [failed(0, 1), failed(0, 2), valid(0, 3), valid(1, 1)],
            max_attempts=5,
            apparatus_reserve=156,
        )
        self.assertEqual(2, projection["valid_statistical_samples"])
        self.assertEqual(2, projection["apparatus_attempts"])
        self.assertEqual(4, projection["request_identities"])
        self.assertEqual(2, projection["next_entry_ordinal"])
        self.assertEqual(1, projection["next_attempt"])
        self.assertIsNone(projection["terminal_reason"])

    def test_entry_and_campaign_limits_stop_without_attempt_bypass(self) -> None:
        entry_exhausted = project_transport_sequence(
            [failed(0, attempt) for attempt in range(1, 6)],
            max_attempts=5,
            apparatus_reserve=156,
        )
        self.assertEqual(
            "entry_attempt_ceiling_exhausted", entry_exhausted["terminal_reason"]
        )
        self.assertIsNone(entry_exhausted["next_attempt"])

        reserve_exhausted = project_transport_sequence(
            [failed(0, 1), valid(0, 2), failed(1, 1)],
            max_attempts=5,
            apparatus_reserve=2,
        )
        self.assertEqual(
            "campaign_apparatus_reserve_exhausted",
            reserve_exhausted["terminal_reason"],
        )

    def test_nonempty_usage_and_nonmatching_failure_are_not_retryable(self) -> None:
        nonempty = host_result(0, 1)
        nonempty["usage"] = {"records": [{"request_id": "provider.1"}]}
        with self.assertRaises(ContractError):
            validate_outcome_free_incomplete_command(
                nonempty, entry_ordinal=0, attempt=1
            )
        wrong = host_result(0, 1)
        wrong["protocol_error"] = {
            "kind": "malformed_record",
            "message": "some other malformed record",
        }
        with self.assertRaises(ContractError):
            validate_outcome_free_incomplete_command(
                wrong, entry_ordinal=0, attempt=1
            )

    def test_nonprefix_events_and_duplicate_request_identities_fail_closed(self) -> None:
        with self.assertRaises(ContractError):
            project_transport_sequence(
                [valid(1, 1)], max_attempts=5, apparatus_reserve=156
            )
        duplicate = failed(0, 1)
        next_event = valid(0, 2)
        next_event["request_id"] = duplicate["request_id"]
        with self.assertRaises(ContractError):
            project_transport_sequence(
                [duplicate, next_event], max_attempts=5, apparatus_reserve=156
            )

    def test_indexed_plan_audit_binds_receipt_bytes_and_natural_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan_path = root / "plan.json"
            index_path = root / "artifacts/index.jsonl"
            entry = {
                "entry_id": "entry.test-0",
                "entry_ordinal": 0,
                "disposition": "execute",
                "attempt_policy": self.policy["runner_attempt_policy"],
            }
            plan = {
                "plan_id": "plan.test",
                "entries": [entry],
                "artifacts": {"root": "artifacts", "index_relpath": "index.jsonl"},
            }
            plan_path.write_bytes(canonical_bytes(plan))
            attempt_root = root / "artifacts/entries/entry.test-0/attempt-0001"
            attempt_root.mkdir(parents=True)
            receipt = {
                "run": {
                    "entry_id": entry["entry_id"],
                    "entry_ordinal": 0,
                    "attempt": 1,
                    "request_id": "request.0.1.execute_case",
                    "valid": False,
                    "error": "official_transient",
                    "terminal": "interrupted",
                    "completion_origin": "resume_seal",
                },
                "usage": {"records": []},
            }
            receipt_path = attempt_root / "receipt.json"
            receipt_path.write_bytes(canonical_bytes(receipt))
            (attempt_root / "host-stdout.jsonl").write_bytes(
                canonical_bytes(host_result(0, 1)) + b"\n"
            )
            relative = "entries/entry.test-0/attempt-0001"
            rows = [
                {
                    "record_type": "index_header",
                    "plan_id": plan["plan_id"],
                    "plan_digest": content_hash(plan_path.read_bytes()),
                },
                {
                    "record_type": "attempt",
                    "entry_id": entry["entry_id"],
                    "artifact_dir": relative,
                    "receipt": {
                        "path": f"{relative}/receipt.json",
                        "digest": content_hash(receipt_path.read_bytes()),
                    },
                },
            ]
            index_path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
            projection = audit_plan_transport(plan_path, index_path, self.policy)
            self.assertEqual(1, projection["indexed_attempts"])
            self.assertEqual(1, projection["apparatus_attempts"])
            self.assertEqual(2, projection["next_attempt"])
            rows[1]["entry_id"] = "entry.test-1"
            index_path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))
            with self.assertRaises(ContractError):
                audit_plan_transport(plan_path, index_path, self.policy)

    def test_policy_is_versioned_and_legacy_budget_replays_unchanged(self) -> None:
        original = deepcopy(self.policy)
        self.assertEqual(
            {
                "max_attempts": 5,
                "retryable_apparatus_classes": ["official_transient"],
                "backoff_seconds": 0,
            },
            materialized_attempt_policy(self.policy),
        )
        self.assertEqual(original, self.policy)
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "provider_requests": 3644,
                "execute": 1752,
                "model_grade": 1880,
                "calibration": 64,
                "calibration_attempts": 128,
            },
            qualification_request_ceilings(
                index,
                repository_root=ROOT,
                campaign_root=ROOT,
                probe_count=6,
            ),
        )
        historical = {
            "schema_version": "model-evolution-campaign/3",
            "campaign_id": "campaign-test",
        }
        schema = json.loads(
            (ROOT / "evaluation/model-evolution/schemas/campaign-v3.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertIn("apparatus_retry_policy", schema["properties"])
        self.assertNotIn("apparatus_retry_policy", schema["required"])
        self.assertEqual("model-evolution-campaign/3", historical["schema_version"])
        validate_document(self.policy, "apparatus_retry_policy")

    def test_campaign_policy_applies_to_all_registered_evidence_roles_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "apparatus-policy.json"
            path.write_bytes(canonical_bytes(self.policy))
            campaign = {
                "apparatus_retry_policy": {
                    "root": "campaign",
                    "path": path.name,
                    "schema_version": self.policy["schema_version"],
                }
            }
            for role in ("target_current", "target_prior", "target_holdout"):
                self.assertEqual(
                    self.policy["runner_attempt_policy"],
                    _campaign_runner_attempt_policy(
                        campaign,
                        role=role,
                        repository_root=root,
                        campaign_root=root,
                    ),
                )
            self.assertIsNone(
                _campaign_runner_attempt_policy(
                    campaign,
                    role="target_candidate",
                    repository_root=root,
                    campaign_root=root,
                )
            )


if __name__ == "__main__":
    unittest.main()
