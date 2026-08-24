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
    campaign_reserve_projection,
    derive_retry_budget,
    audit_plan_transport,
    materialized_attempt_policy,
    plan_registration_projection,
    project_transport_sequence,
    validate_apparatus_retry_policy,
    validate_outcome_free_incomplete_command,
)
from _model_evolution_campaign import (  # noqa: E402
    qualification_request_ceilings,
    require_qualification_request_ceilings,
)
from _model_evolution_contract import (  # noqa: E402
    BUDGET_FIELDS,
    ContractError,
    canonical_bytes,
    content_hash,
    validate_document,
)
from _model_evolution_state import (  # noqa: E402
    StateError,
    register_plan,
    reserve_budget,
)
from _model_evolution_materialization import (  # noqa: E402
    _campaign_runner_attempt_policy,
)


POLICY_PATH = (
    ROOT
    / "evaluation/model-evolution/confirmatory-v2/apparatus-retry-policy-v1.json"
)
POLICY_V2_PATH = (
    ROOT
    / "evaluation/model-evolution/confirmatory-v2/apparatus-retry-policy-v2.json"
)
INDEX_PATH = (
    ROOT / "evaluation/model-evolution/confirmatory-v1/sentinel-index-v3.json"
)


def host_result(
    ordinal: int,
    attempt: int,
    *,
    message: str | None = None,
) -> dict[str, object]:
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
            "message": message
            or (
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


def failed(
    ordinal: int,
    attempt: int,
    *,
    message: str | None = None,
) -> dict[str, object]:
    return {
        "entry_ordinal": ordinal,
        "attempt": attempt,
        "request_id": f"request.{ordinal}.{attempt}.execute_case",
        "valid": False,
        "host_result": host_result(ordinal, attempt, message=message),
    }


def valid(ordinal: int, attempt: int) -> dict[str, object]:
    return {
        "entry_ordinal": ordinal,
        "attempt": attempt,
        "request_id": f"request.{ordinal}.{attempt}.execute_case",
        "valid": True,
    }


def zero_attempt_status(
    entries: int, *, max_attempts: int = 5, model_grade_entries: int | None = None
) -> dict[str, object]:
    raw = entries * max_attempts
    raw_model_grade = (
        entries if model_grade_entries is None else model_grade_entries
    ) * max_attempts
    return {
        "selected_entries": entries,
        "execute_entries": entries,
        "indexed_attempts": 0,
        "completed_entries": 0,
        "invalid_attempts": 0,
        "remaining_entries": entries,
        "active_attempts": [],
        "recoverable_attempts": [],
        "next_pass_new_attempts": entries,
        "worst_case_remaining_attempts": raw,
        "execute_case_request_ceiling": raw,
        "model_grade_request_ceiling": raw_model_grade,
    }


def budget_state() -> dict[str, object]:
    ceiling = {field: 0 for field in BUDGET_FIELDS}
    ceiling.update(
        {
            "execute": 1032,
            "model_grade": 1160,
            "provider_requests": 2204,
        }
    )
    reserved = {field: 0 for field in BUDGET_FIELDS}
    return {
        "phase": "calibration_ready",
        "plans": [],
        "budgets": {"ceiling": ceiling, "reserved": reserved},
        "candidate": None,
        "profiles": {"predecessor": None},
        "skill_evidence": {
            skill_id: {"grader_calibration": {"root": "campaign", "path": "x"}}
            for skill_id in (
                "long-document-segmented-writing",
                "skill-evaluator",
                "software-quality-workflows",
                "writing-plans",
            )
        },
    }


def plan_record(role: str, skill_id: str, entries: int) -> dict[str, object]:
    return {
        "role": role,
        "skill_id": skill_id,
        "plan": {"root": "campaign", "path": f"plans/{role}/{skill_id}.json"},
        "plan_digest": f"sha256:{role}.{skill_id}",
        "host_id": "host.test",
        "host_version": "1",
        "execute_ceiling": entries,
        "model_grade_ceiling": entries,
        "runner_status": {"completed": 0, "total": entries, "failed": 0},
    }


class ApparatusRetryContract(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.policy_v2 = json.loads(POLICY_V2_PATH.read_text(encoding="utf-8"))

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

    def test_shared_reserve_and_nominal_plan_reservations_close_exactly(self) -> None:
        state = budget_state()
        state["state_revision"] = 0
        reserve_budget(
            state,
            {"model_grade": 128, "provider_requests": 128},
        )
        reserve_budget(state, campaign_reserve_projection(self.policy))
        self.assertEqual(
            {"execute": 156, "model_grade": 284, "provider_requests": 440},
            {
                field: state["budgets"]["reserved"][field]
                for field in ("execute", "model_grade", "provider_requests")
            },
        )
        reserve_budget(state, {"provider_requests": 12})
        self.assertEqual(452, state["budgets"]["reserved"]["provider_requests"])

        entries = {
            "long-document-segmented-writing": 36,
            "skill-evaluator": 288,
            "software-quality-workflows": 54,
            "writing-plans": 36,
        }
        register_plan(
            state,
            plan_record("target_current", "skill-evaluator", 288),
        )
        self.assertEqual(
            {"execute": 444, "model_grade": 572, "provider_requests": 1028},
            {
                field: state["budgets"]["reserved"][field]
                for field in ("execute", "model_grade", "provider_requests")
            },
        )
        for skill_id, count in entries.items():
            if skill_id != "skill-evaluator":
                register_plan(
                    state,
                    plan_record("target_current", skill_id, count),
                )
        state["phase"] = "decision_ready"
        for skill_id, count in entries.items():
            register_plan(state, plan_record("target_prior", skill_id, count))
        state["phase"] = "final_plugin_ready"
        for skill_id in entries:
            register_plan(state, plan_record("target_holdout", skill_id, 12))
        self.assertEqual(
            {"execute": 1032, "model_grade": 1160, "provider_requests": 2204},
            {
                field: state["budgets"]["reserved"][field]
                for field in ("execute", "model_grade", "provider_requests")
            },
        )
        snapshot = deepcopy(state["budgets"]["reserved"])
        with self.assertRaises(StateError):
            reserve_budget(state, campaign_reserve_projection(self.policy))
        self.assertEqual(snapshot, state["budgets"]["reserved"])

    def test_plan_projection_preserves_raw_ceiling_and_fails_closed(self) -> None:
        status = zero_attempt_status(288)
        projection = plan_registration_projection(status, self.policy)
        self.assertEqual(288, projection["execute"])
        self.assertEqual(288, projection["model_grade"])
        self.assertEqual(288, projection["initial_attempt_budget"])
        self.assertEqual(1440, projection["raw_execute_ceiling"])
        self.assertEqual(1440, projection["raw_model_grade_ceiling"])

        long_document = plan_registration_projection(
            zero_attempt_status(36, model_grade_entries=30), self.policy
        )
        self.assertEqual(36, long_document["execute"])
        self.assertEqual(36, long_document["model_grade"])
        self.assertEqual(180, long_document["raw_execute_ceiling"])
        self.assertEqual(150, long_document["raw_model_grade_ceiling"])

        deterministic_only = plan_registration_projection(
            zero_attempt_status(8, model_grade_entries=0), self.policy
        )
        self.assertEqual(8, deterministic_only["execute"])
        self.assertEqual(8, deterministic_only["model_grade"])
        self.assertEqual(0, deterministic_only["raw_model_grade_ceiling"])

        mutations = (
            ("indexed_attempts", 1),
            ("completed_entries", 1),
            ("invalid_attempts", 1),
            ("active_attempts", ["attempt"]),
            ("recoverable_attempts", ["attempt"]),
            ("next_pass_new_attempts", 287),
            ("execute_case_request_ceiling", 1439),
            ("model_grade_request_ceiling", 1439),
            ("model_grade_request_ceiling", 1445),
        )
        for field, value in mutations:
            changed = dict(status)
            changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(
                ContractError
            ):
                plan_registration_projection(changed, self.policy)

    def test_replacement_keeps_shared_reserve_and_budget_limits_are_atomic(self) -> None:
        state = budget_state()
        state["state_revision"] = 4
        reserve_budget(
            state,
            {"model_grade": 128, "provider_requests": 128},
        )
        reserve_budget(state, campaign_reserve_projection(self.policy))
        reserve_budget(state, {"provider_requests": 12})
        record = plan_record("target_current", "skill-evaluator", 288)
        register_plan(state, record)
        before = deepcopy(state["budgets"]["reserved"])
        successor = deepcopy(record)
        successor["plan"] = {
            "root": "campaign",
            "path": "plans/target_current/skill-evaluator-successor.json",
        }
        register_plan(
            state,
            successor,
            replace_existing=True,
            old_runner_stopped=True,
            old_runner_status=zero_attempt_status(288),
            new_runner_status=zero_attempt_status(288),
        )
        self.assertEqual(before, state["budgets"]["reserved"])

        for field in ("execute", "model_grade", "provider_requests"):
            changed = budget_state()
            changed["budgets"]["ceiling"][field] = 1
            snapshot = deepcopy(changed["budgets"]["reserved"])
            with self.subTest(field=field), self.assertRaises(StateError):
                reserve_budget(changed, {field: 2})
            self.assertEqual(snapshot, changed["budgets"]["reserved"])

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

    def test_v2_accepts_multiple_same_type_records_but_v1_rejects_them(self) -> None:
        validate_apparatus_retry_policy(self.policy_v2)
        multiple = host_result(
            0,
            1,
            message=(
                "Codex stream has incomplete items: stdout record 12 "
                "(item.started/command_execution), stdout record 23 "
                "(item.started/command_execution)"
            ),
        )
        validate_outcome_free_incomplete_command(
            multiple,
            entry_ordinal=0,
            attempt=1,
            allow_multiple_incomplete_commands=True,
        )
        with self.assertRaises(ContractError):
            validate_outcome_free_incomplete_command(
                multiple, entry_ordinal=0, attempt=1
            )
        mixed = deepcopy(multiple)
        mixed["protocol_error"]["message"] = (
            "Codex stream has incomplete items: stdout record 12 "
            "(item.started/command_execution), stdout record 23 "
            "(item.completed/command_execution)"
        )
        with self.assertRaises(ContractError):
            validate_outcome_free_incomplete_command(
                mixed,
                entry_ordinal=0,
                attempt=1,
                allow_multiple_incomplete_commands=True,
            )

    def test_v2_rejects_effects_dirty_cleanup_and_bad_reset_custody(self) -> None:
        for field, value in (
            ("actions", [{"kind": "write"}]),
            ("artifacts", [{"path": "output.txt"}]),
            ("assertions", [{"claim": "result"}]),
            ("handoffs", [{"status": "result"}]),
            ("principals", [{"id": "main"}]),
            ("state", [{"phase": "changed"}]),
        ):
            changed = host_result(0, 1)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate_outcome_free_incomplete_command(
                    changed,
                    entry_ordinal=0,
                    attempt=1,
                    allow_multiple_incomplete_commands=True,
                )
        dirty = host_result(0, 1)
        dirty["cleanup"] = {"status": "dirty"}
        with self.assertRaises(ContractError):
            validate_outcome_free_incomplete_command(
                dirty,
                entry_ordinal=0,
                attempt=1,
                allow_multiple_incomplete_commands=True,
            )

    def test_v2_transport_prefix_and_attempt_ceiling_remain_bounded(self) -> None:
        message = (
            "Codex stream has incomplete items: stdout record 12 "
            "(item.started/command_execution), stdout record 23 "
            "(item.started/command_execution)"
        )
        projection = project_transport_sequence(
            [
                failed(0, 1, message=message),
                failed(0, 2, message=message),
                valid(0, 3),
            ],
            max_attempts=5,
            apparatus_reserve=156,
            allow_multiple_incomplete_commands=True,
        )
        self.assertEqual(1, projection["valid_statistical_samples"])
        self.assertEqual(2, projection["apparatus_attempts"])
        self.assertEqual(3, projection["request_identities"])
        exhausted = project_transport_sequence(
            [failed(0, attempt, message=message) for attempt in range(1, 6)],
            max_attempts=5,
            apparatus_reserve=156,
            allow_multiple_incomplete_commands=True,
        )
        self.assertEqual(
            "entry_attempt_ceiling_exhausted", exhausted["terminal_reason"]
        )

    def test_unknown_apparatus_policy_version_fails_closed(self) -> None:
        unknown = deepcopy(self.policy_v2)
        unknown["schema_version"] = "model-evolution-apparatus-retry-policy/99"
        with self.assertRaises(ContractError):
            validate_apparatus_retry_policy(unknown)

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

    def test_v2_index_audit_requires_multiple_record_reset_custody(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan_path = root / "plan.json"
            index_path = root / "artifacts/index.jsonl"
            entry = {
                "entry_id": "entry.test-0",
                "entry_ordinal": 0,
                "disposition": "execute",
                "attempt_policy": self.policy_v2["runner_attempt_policy"],
            }
            plan = {
                "plan_id": "plan.test-v2",
                "entries": [entry],
                "artifacts": {"root": "artifacts", "index_relpath": "index.jsonl"},
            }
            plan_path.write_bytes(canonical_bytes(plan))
            attempt_root = root / "artifacts/entries/entry.test-0/attempt-0001"
            (attempt_root / "reset").mkdir(parents=True)
            (attempt_root / "workspace").mkdir()
            proof_path = attempt_root / "workspace/reset-proof.json"
            proof_path.write_bytes(
                canonical_bytes(
                    {"capability": "state_snapshot_reset", "workspace": "contained"}
                )
            )
            reset = host_result(0, 1)
            reset["envelope"]["request_kind"] = "probe_capability"
            reset["terminal_status"] = "completed"
            reset["protocol_error"] = None
            reset["artifacts"] = [
                {
                    "digest": content_hash(proof_path.read_bytes()),
                    "encoding": "utf-8",
                    "path": "workspace/reset-proof.json",
                }
            ]
            (attempt_root / "reset/host-stdout.jsonl").write_bytes(
                canonical_bytes(reset) + b"\n"
            )
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
            multi = host_result(
                0,
                1,
                message=(
                    "Codex stream has incomplete items: stdout record 12 "
                    "(item.started/command_execution), stdout record 23 "
                    "(item.started/command_execution)"
                ),
            )
            (attempt_root / "host-stdout.jsonl").write_bytes(
                canonical_bytes(multi) + b"\n"
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
            index_path.write_bytes(
                b"".join(canonical_bytes(row) + b"\n" for row in rows)
            )
            projection = audit_plan_transport(plan_path, index_path, self.policy_v2)
            self.assertEqual(1, projection["apparatus_attempts"])
            proof_path.write_bytes(
                canonical_bytes(
                    {"capability": "state_snapshot_reset", "workspace": "dirty"}
                )
            )
            with self.assertRaises(ContractError):
                audit_plan_transport(plan_path, index_path, self.policy_v2)

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
