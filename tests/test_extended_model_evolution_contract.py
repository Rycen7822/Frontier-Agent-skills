from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from _model_evolution_contract import (  # noqa: E402
    ContractError,
    SKILL_IDS,
    _is_partial_calibration_correction,
    build_initial_campaign,
    evaluator_evidence_status,
    make_binding,
    prepare_predecessor,
    prepare_supersedes,
    project_observed_host,
    project_qualification,
    render_qualification_markdown,
    resolve_binding,
    validate_document,
    validate_bundle_build,
    with_self_hash,
)
from model_evolution_test_support import (  # noqa: E402
    mark_probe_passed,
    materialize_apparatus_report,
    materialize_bootstrap_evidence,
    materialize_budget_approval,
    materialize_campaign,
    write_json,
)
from skill_evaluator_test_support import (  # noqa: E402
    canonical_hash,
    make_v5_schema_examples,
)


def closed_transition_report() -> dict:
    value = make_v5_schema_examples()["comparison-report-v1.schema.json"]
    value.update(
        {
            "kind": "model_transition",
            "comparison_id": "transition-example",
            "registration_status": "declared_pre_registered",
            "authority_eligibility": "eligible",
            "result": {
                "kind": "model_transition",
                "mode": "direct",
                "classification": "retained_specialized_value",
                "classification_metric_ids": [],
            },
        }
    )
    return with_self_hash(value, "comparison_report_hash")


class ModelEvolutionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = materialize_campaign(Path(self.temporary.name))

    def _blocked_qualification(self) -> dict:
        return project_qualification(
            self.fixture["campaign"],
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            observed_as_of="2026-08-03T00:00:00Z",
            valid_until="2026-08-04T00:00:00Z",
        )

    def test_closed_schemas_and_self_hashes(self) -> None:
        documents = {
            "budget_approval": json.loads(
                materialize_budget_approval(
                    self.fixture,
                    self.fixture["campaign"],
                ).read_text()
            ),
            "campaign": self.fixture["campaign"],
            "interaction_probes": json.loads(
                self.fixture["paths"]["probe_set"].read_text()
            ),
            "sentinel_index": json.loads(self.fixture["paths"]["sentinel"].read_text()),
            "qualification": self._blocked_qualification(),
        }
        hash_fields = {
            "budget_approval": "approval_hash",
            "campaign": "campaign_hash",
            "interaction_probes": "probe_set_hash",
            "sentinel_index": "sentinel_hash",
            "qualification": "qualification_hash",
        }
        for name, value in documents.items():
            with self.subTest(name=name):
                validate_document(value, name)
                tampered = copy.deepcopy(value)
                tampered[hash_fields[name]] = "sha256:" + "0" * 64
                with self.assertRaisesRegex(ContractError, "canonical content"):
                    validate_document(tampered, name)
                unknown = copy.deepcopy(value)
                unknown["unknown"] = True
                unknown = with_self_hash(unknown, hash_fields[name])
                with self.assertRaisesRegex(ContractError, "schema violation"):
                    validate_document(unknown, name)

    def test_bindings_reject_escape_symlink_and_tamper(self) -> None:
        repository_root = self.fixture["repository_root"]
        campaign_root = self.fixture["campaign_root"]
        path = repository_root / "bound.txt"
        path.write_text("bound\n", encoding="utf-8")
        binding = make_binding(
            path,
            root="repository",
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        self.assertEqual(resolve_binding(binding, repository_root, campaign_root), path)
        escaped = dict(binding, path="../bound.txt")
        with self.assertRaisesRegex(ContractError, "escapes"):
            resolve_binding(escaped, repository_root, campaign_root)
        link = repository_root / "bound-link.txt"
        link.symlink_to(path)
        with self.assertRaisesRegex(ContractError, "non-symlink"):
            make_binding(
                link,
                root="repository",
                repository_root=repository_root,
                campaign_root=campaign_root,
            )
        path.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "hash differs"):
            resolve_binding(binding, repository_root, campaign_root)

    def test_exact_four_skill_identity_is_closed(self) -> None:
        campaign = copy.deepcopy(self.fixture["campaign"])
        campaign["product"]["skills"].pop("writing-plans")
        campaign = with_self_hash(campaign, "campaign_hash")
        with self.assertRaisesRegex(ContractError, "schema violation"):
            validate_document(campaign, "campaign")

    def test_probe_contract_rejects_duplicates_model_names_and_seventh_row(
        self,
    ) -> None:
        probes = json.loads(self.fixture["paths"]["probe_set"].read_text())
        duplicate = copy.deepcopy(probes)
        duplicate["probes"].append(copy.deepcopy(duplicate["probes"][0]))
        duplicate = with_self_hash(duplicate, "probe_set_hash")
        with self.assertRaisesRegex(ContractError, "IDs must be unique"):
            validate_document(duplicate, "interaction_probes")

        named = copy.deepcopy(probes)
        named["probes"][0]["prompt"] = "Use GPT behavior."
        named = with_self_hash(named, "probe_set_hash")
        with self.assertRaisesRegex(ContractError, "schema violation"):
            validate_document(named, "interaction_probes")

        too_many = copy.deepcopy(probes)
        capabilities = [
            "force_load",
            "natural_routing",
            "multi_turn",
            "principal_tracing",
            "usage_capture",
            "action_authorization_trace",
            "force_load",
        ]
        too_many["probes"] = []
        for index, capability in enumerate(capabilities):
            row = copy.deepcopy(probes["probes"][0])
            row["probe_id"] = f"probe-{index}"
            row["capability"] = capability
            too_many["probes"].append(row)
        too_many = with_self_hash(too_many, "probe_set_hash")
        with self.assertRaisesRegex(ContractError, "schema violation"):
            validate_document(too_many, "interaction_probes")

    def test_external_schema_resolution_is_local_only(self) -> None:
        path = write_json(
            self.fixture["campaign_root"] / "summary-local.json",
            with_self_hash(
                make_v5_schema_examples()["analysis-summary-v4.schema.json"],
                "summary_hash",
            ),
        )
        with mock.patch(
            "urllib.request.urlopen", side_effect=AssertionError("network attempted")
        ):
            self.assertEqual(
                evaluator_evidence_status(path, kind="current_summary"), "pass"
            )

    def test_predecessor_requires_a_closed_cycle_and_bound_transition(self) -> None:
        ready = materialize_bootstrap_evidence(self.fixture)
        historical = self.fixture["repository_root"] / ".work/predecessor"
        cycle_path = write_json(historical / "campaign.json", ready)
        comparison = closed_transition_report()
        comparison_path = write_json(historical / "comparison.json", comparison)
        cycle = make_binding(
            cycle_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        comparison_binding = make_binding(
            comparison_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        predecessor = prepare_predecessor(
            cycle_binding=cycle,
            host_binding=self.fixture["bindings"]["host"],
            comparison_binding=comparison_binding,
            qualification_binding=None,
            current_bundle_id=ready["product"]["bundle_id"],
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        self.assertEqual(
            predecessor["comparison_hash"], comparison["comparison_report_hash"]
        )
        unclosed = copy.deepcopy(ready)
        unclosed["phase"] = "decision_ready"
        write_json(cycle_path, with_self_hash(unclosed, "campaign_hash"))
        cycle = make_binding(
            cycle_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "not closed"):
            prepare_predecessor(
                cycle_binding=cycle,
                host_binding=self.fixture["bindings"]["host"],
                comparison_binding=comparison_binding,
                qualification_binding=None,
                current_bundle_id=ready["product"]["bundle_id"],
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

    def test_supersedes_imports_budget_once_from_blocked_same_host(self) -> None:
        old = copy.deepcopy(self.fixture["campaign"])
        old["budgets"]["reserved"]["provider_requests"] = 2
        old["budgets"]["observed"]["provider_requests"] = 1
        old = with_self_hash(old, "campaign_hash")
        historical = self.fixture["repository_root"] / ".work/blocked"
        shutil.copytree(self.fixture["campaign_root"], historical)
        qualification = project_qualification(
            old,
            repository_root=self.fixture["repository_root"],
            campaign_root=historical,
            observed_as_of="2026-08-03T00:00:00Z",
            valid_until="2026-08-04T00:00:00Z",
        )
        for skill_id in SKILL_IDS:
            del old["skill_evidence"][skill_id]["grader_calibration"]
        old["skill_evidence"]["grader_calibration"] = None
        old = with_self_hash(old, "campaign_hash")
        qualification["campaign_hash"] = old["campaign_hash"]
        qualification = with_self_hash(qualification, "qualification_hash")
        old_path = write_json(historical / "campaign.json", old)
        write_json(historical / "qualification/qualification.json", qualification)
        old_binding = make_binding(
            old_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        supersedes = prepare_supersedes(
            campaign_binding=old_binding,
            target_host_binding=self.fixture["bindings"]["host"],
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        self.assertEqual(supersedes["imported_reserved"]["provider_requests"], 2)
        self.assertEqual(supersedes["imported_observed"]["provider_requests"], 1)
        repaired_host = json.loads(self.fixture["paths"]["host"].read_text())
        repaired_host["identity"]["adapter"]["sha256"] = "sha256:" + "7" * 64
        repaired_host["identity"]["execution"]["skill_hash"] = (
            "sha256:" + "6" * 64
        )
        timeout_index = repaired_host["command"]["argv"].index("--timeout") + 1
        repaired_host["command"]["argv"][timeout_index] = "10"
        repaired_host["manifest_hash"] = canonical_hash(
            {
                key: value
                for key, value in repaired_host.items()
                if key != "manifest_hash"
            }
        )
        repaired_path = write_json(
            self.fixture["campaign_root"] / "inputs/repaired-host.json",
            repaired_host,
        )
        repaired_binding = make_binding(
            repaired_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        prepare_supersedes(
            campaign_binding=old_binding,
            target_host_binding=repaired_binding,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        repaired_host["command"]["argv"][timeout_index] = "1"
        repaired_host["manifest_hash"] = canonical_hash(
            {
                key: value
                for key, value in repaired_host.items()
                if key != "manifest_hash"
            }
        )
        write_json(repaired_path, repaired_host)
        shorter_timeout_binding = make_binding(
            repaired_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "different Host"):
            prepare_supersedes(
                campaign_binding=old_binding,
                target_host_binding=shorter_timeout_binding,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )
        repaired_host["command"]["argv"][timeout_index] = "10"
        repaired_host["identity"]["execution"]["model"] = "different-model"
        repaired_host["manifest_hash"] = canonical_hash(
            {
                key: value
                for key, value in repaired_host.items()
                if key != "manifest_hash"
            }
        )
        write_json(repaired_path, repaired_host)
        different_binding = make_binding(
            repaired_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "different Host"):
            prepare_supersedes(
                campaign_binding=old_binding,
                target_host_binding=different_binding,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )
        product = {
            name: json.loads(self.fixture["paths"][name].read_text())
            for name in ("bundle_manifest", "bundle_build", "static_report")
        }
        repair = build_initial_campaign(
            campaign_id="repair-campaign",
            git_identity={"commit": "a" * 40, "tree": "b" * 40},
            bundle_manifest=product["bundle_manifest"],
            bundle_manifest_binding=self.fixture["bindings"]["bundle_manifest"],
            bundle_build=product["bundle_build"],
            bundle_build_binding=self.fixture["bindings"]["bundle_build"],
            plugin_build_binding=self.fixture["bindings"]["plugin_build"],
            plugin_root=self.fixture["campaign"]["product"]["plugin_root"],
            plugin_tree_hash=self.fixture["campaign"]["product"]["plugin_tree"],
            calibration_requests=self.fixture["campaign"]["product"][
                "calibration_requests"
            ],
            static_report=product["static_report"],
            static_report_binding=self.fixture["bindings"]["static_report"],
            target_host_binding=self.fixture["bindings"]["host"],
            probe_set_binding=self.fixture["bindings"]["probe_set"],
            sentinel_binding=self.fixture["bindings"]["sentinel"],
            ceilings=self.fixture["campaign"]["budgets"]["ceiling"],
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            supersedes=supersedes,
        )
        self.assertEqual(repair["budgets"]["reserved"]["provider_requests"], 2)
        self.assertEqual(repair["budgets"]["observed"]["provider_requests"], 1)

        repair_root = self.fixture["repository_root"] / ".work/repair"
        shutil.copytree(self.fixture["campaign_root"], repair_root)
        repair_path = write_json(repair_root / "campaign.json", repair)
        write_json(
            repair_root / "qualification/qualification.json",
            project_qualification(
                repair,
                repository_root=self.fixture["repository_root"],
                campaign_root=repair_root,
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            ),
        )
        repair_binding = make_binding(
            repair_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        second = prepare_supersedes(
            campaign_binding=repair_binding,
            target_host_binding=self.fixture["bindings"]["host"],
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        self.assertEqual(second["imported_reserved"], repair["budgets"]["reserved"])

        final = copy.deepcopy(repair)
        final["supersedes"] = second
        final = with_self_hash(final, "campaign_hash")
        final_path = write_json(repair_root / "final-campaign.json", final)
        final_binding = make_binding(
            final_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "depth is exhausted"):
            prepare_supersedes(
                campaign_binding=final_binding,
                target_host_binding=self.fixture["bindings"]["host"],
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

        final["phase"] = "target_profile_ready"
        final["apparatus_report"] = materialize_apparatus_report(
            self.fixture, final
        )
        final["profiles"]["target_observed"] = self.fixture["bindings"]["host"]
        mark_probe_passed(final, self.fixture)
        final = with_self_hash(final, "campaign_hash")
        final_root = self.fixture["repository_root"] / ".work/final"
        shutil.copytree(self.fixture["campaign_root"], final_root)
        final_path = write_json(final_root / "campaign.json", final)
        write_json(
            final_root / "qualification/qualification.json",
            project_qualification(
                final,
                repository_root=self.fixture["repository_root"],
                campaign_root=final_root,
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            ),
        )
        final_binding = make_binding(
            final_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        correction = prepare_supersedes(
            campaign_binding=final_binding,
            target_host_binding=self.fixture["bindings"]["host"],
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        self.assertEqual(
            final["budgets"]["reserved"], correction["imported_reserved"]
        )

        corrected = copy.deepcopy(final)
        corrected["supersedes"] = correction
        corrected = with_self_hash(corrected, "campaign_hash")
        corrected_root = self.fixture["repository_root"] / ".work/corrected"
        shutil.copytree(self.fixture["campaign_root"], corrected_root)
        corrected_path = write_json(corrected_root / "campaign.json", corrected)
        corrected_binding = make_binding(
            corrected_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "requires a failed-request receipt"):
            prepare_supersedes(
                campaign_binding=corrected_binding,
                target_host_binding=self.fixture["bindings"]["host"],
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

        qualification_path = write_json(
            corrected_root / "qualification/qualification.json",
            project_qualification(
                corrected,
                repository_root=self.fixture["repository_root"],
                campaign_root=corrected_root,
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            ),
        )
        preparation_path = write_json(
            corrected_root / "calibration/preparation.json",
            {"preparation": "bound"},
        )
        result_path = write_json(
            corrected_root / "calibration/terminals/001/host-stdout.jsonl",
            {
                "actions": [],
                "artifacts": [],
                "assertions": [],
                "cleanup": {"status": "clean"},
                "context": {"bytes": 0},
                "envelope": {
                    "entry_id": "calibration-01",
                    "entry_ordinal": 0,
                    "request_kind": "model_grade",
                },
                "failure_class": "model_task_timeout",
                "handoffs": [],
                "principals": [],
                "record_type": "skill-evaluator-host-result/1",
                "request_hash": "sha256:" + "1" * 64,
                "state": [],
                "terminal": True,
                "terminal_status": "timeout",
                "usage": {"records": []},
            },
        )
        stderr_path = corrected_root / "calibration/terminals/001/host-stderr.txt"
        stderr_path.write_text("pre-turn failure\n", encoding="utf-8")
        receipt = with_self_hash({
            "schema_version": "model-evolution-failure-receipt/1",
            "campaign_hash": corrected["campaign_hash"],
            "qualification": make_binding(
                qualification_path,
                root="campaign",
                repository_root=self.fixture["repository_root"],
                campaign_root=corrected_root,
            ),
            "preparation": make_binding(
                preparation_path,
                root="campaign",
                repository_root=self.fixture["repository_root"],
                campaign_root=corrected_root,
            ),
            "skill_id": "long-document-segmented-writing",
            "request_kind": "model_grade",
            "classification": "host_failed_before_completed_turn",
            "request_count": 1,
            "outcomes": {"timeout": 1, "failed": 0},
            "requests": [{
                "entry_ordinal": 0,
                "entry_id": "calibration-01",
                "request_hash": "sha256:" + "1" * 64,
                "terminal_status": "timeout",
                "failure_class": "model_task_timeout",
                "host_result": make_binding(
                    result_path,
                    root="campaign",
                    repository_root=self.fixture["repository_root"],
                    campaign_root=corrected_root,
                ),
                "host_stderr": make_binding(
                    stderr_path,
                    root="campaign",
                    repository_root=self.fixture["repository_root"],
                    campaign_root=corrected_root,
                ),
            }],
        }, "failure_receipt_hash")
        validate_document(receipt, "failure_receipt")
        receipt_path = write_json(
            corrected_root / "calibration/failure-receipt.json",
            receipt,
        )
        receipt_binding = make_binding(
            receipt_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        final_repair = prepare_supersedes(
            campaign_binding=corrected_binding,
            target_host_binding=self.fixture["bindings"]["host"],
            failure_receipt_binding=receipt_binding,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        self.assertEqual(
            corrected["budgets"]["reserved"]["model_grade"] + 1,
            final_repair["imported_reserved"]["model_grade"],
        )
        self.assertEqual(receipt_binding, final_repair["failure_receipt"])

        tampered_receipt = copy.deepcopy(receipt)
        tampered_receipt["requests"][0]["request_hash"] = "sha256:" + "3" * 64
        tampered_receipt = with_self_hash(
            tampered_receipt,
            "failure_receipt_hash",
        )
        tampered_path = write_json(
            corrected_root / "calibration/tampered-failure-receipt.json",
            tampered_receipt,
        )
        tampered_binding = make_binding(
            tampered_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "differs from Host evidence"):
            prepare_supersedes(
                campaign_binding=corrected_binding,
                target_host_binding=self.fixture["bindings"]["host"],
                failure_receipt_binding=tampered_binding,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

        exhausted = copy.deepcopy(corrected)
        exhausted["supersedes"] = final_repair
        exhausted["budgets"]["reserved"] = copy.deepcopy(
            final_repair["imported_reserved"]
        )
        exhausted["budgets"]["observed"] = copy.deepcopy(
            final_repair["imported_observed"]
        )
        exhausted = with_self_hash(exhausted, "campaign_hash")
        exhausted_root = self.fixture["repository_root"] / ".work/exhausted"
        shutil.copytree(corrected_root, exhausted_root)
        exhausted_path = write_json(exhausted_root / "campaign.json", exhausted)
        exhausted_qualification = write_json(
            exhausted_root / "qualification/qualification.json",
            project_qualification(
                exhausted,
                repository_root=self.fixture["repository_root"],
                campaign_root=exhausted_root,
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            ),
        )
        exhausted_binding = make_binding(
            exhausted_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        exhausted_receipt = copy.deepcopy(receipt)
        exhausted_receipt["campaign_hash"] = exhausted["campaign_hash"]
        exhausted_receipt["qualification"] = make_binding(
            exhausted_qualification,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=exhausted_root,
        )
        exhausted_receipt = with_self_hash(
            exhausted_receipt,
            "failure_receipt_hash",
        )
        exhausted_receipt_path = write_json(
            exhausted_root / "calibration/final-failure-receipt.json",
            exhausted_receipt,
        )
        exhausted_receipt_binding = make_binding(
            exhausted_receipt_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        last_repair = prepare_supersedes(
            campaign_binding=exhausted_binding,
            target_host_binding=self.fixture["bindings"]["host"],
            failure_receipt_binding=exhausted_receipt_binding,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        self.assertEqual(
            exhausted["budgets"]["reserved"]["model_grade"] + 1,
            last_repair["imported_reserved"]["model_grade"],
        )

        terminal = copy.deepcopy(exhausted)
        terminal["supersedes"] = last_repair
        terminal["budgets"]["reserved"] = copy.deepcopy(
            last_repair["imported_reserved"]
        )
        terminal["budgets"]["observed"] = copy.deepcopy(
            last_repair["imported_observed"]
        )
        terminal = with_self_hash(terminal, "campaign_hash")
        terminal_path = write_json(
            exhausted_root / "terminal-campaign.json",
            terminal,
        )
        terminal_binding = make_binding(
            terminal_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "depth is exhausted"):
            prepare_supersedes(
                campaign_binding=terminal_binding,
                target_host_binding=self.fixture["bindings"]["host"],
                failure_receipt_binding=exhausted_receipt_binding,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

        probe_only = copy.deepcopy(terminal)
        probe_only["phase"] = "apparatus_ready"
        probe_only["interaction_probes"]["blocker"] = (
            "critical interaction probes did not pass: natural_routing"
        )
        probe_only["interaction_probes"]["requests"][0][
            "result_status"
        ] = "unknown"
        probe_only = with_self_hash(probe_only, "campaign_hash")
        probe_root = self.fixture["repository_root"] / ".work/probe-contract"
        shutil.copytree(self.fixture["campaign_root"], probe_root)
        probe_path = write_json(probe_root / "campaign.json", probe_only)
        write_json(
            probe_root / "qualification/qualification.json",
            project_qualification(
                probe_only,
                repository_root=self.fixture["repository_root"],
                campaign_root=probe_root,
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            ),
        )
        probe_binding = make_binding(
            probe_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        probe_repair = prepare_supersedes(
            campaign_binding=probe_binding,
            target_host_binding=self.fixture["bindings"]["host"],
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        self.assertEqual(
            probe_only["budgets"]["reserved"],
            probe_repair["imported_reserved"],
        )
        self.assertNotIn("failure_receipt", probe_repair)

        final_probe = copy.deepcopy(probe_only)
        final_probe["supersedes"] = probe_repair
        final_probe = with_self_hash(final_probe, "campaign_hash")
        final_probe_root = (
            self.fixture["repository_root"] / ".work/final-probe-contract"
        )
        shutil.copytree(self.fixture["campaign_root"], final_probe_root)
        final_probe_path = write_json(
            final_probe_root / "campaign.json", final_probe
        )
        write_json(
            final_probe_root / "qualification/qualification.json",
            project_qualification(
                final_probe,
                repository_root=self.fixture["repository_root"],
                campaign_root=final_probe_root,
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            ),
        )
        final_probe_binding = make_binding(
            final_probe_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "depth is exhausted"):
            prepare_supersedes(
                campaign_binding=final_probe_binding,
                target_host_binding=self.fixture["bindings"]["host"],
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

        calibration_blocked = copy.deepcopy(final_probe)
        calibration_blocked["phase"] = "target_profile_ready"
        calibration_blocked["interaction_probes"]["blocker"] = None
        calibration_blocked = with_self_hash(
            calibration_blocked, "campaign_hash"
        )
        calibration_root = (
            self.fixture["repository_root"] / ".work/calibration-contract"
        )
        shutil.copytree(self.fixture["campaign_root"], calibration_root)
        calibration_path = write_json(
            calibration_root / "campaign.json", calibration_blocked
        )
        write_json(
            calibration_root / "qualification/qualification.json",
            project_qualification(
                calibration_blocked,
                repository_root=self.fixture["repository_root"],
                campaign_root=calibration_root,
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            ),
        )
        calibration_binding = make_binding(
            calibration_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(ContractError, "requires a rejection receipt"):
            prepare_supersedes(
                campaign_binding=calibration_binding,
                target_host_binding=self.fixture["bindings"]["host"],
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )
        rejection_path = write_json(
            calibration_root / "calibration/rejection.json", {"bound": True}
        )
        rejection_binding = make_binding(
            rejection_path,
            root="repository",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with mock.patch(
            "_model_evolution_contract._calibration_rejection_request_count",
            return_value=16,
        ):
            correction = prepare_supersedes(
                campaign_binding=calibration_binding,
                target_host_binding=self.fixture["bindings"]["host"],
                calibration_rejection_receipt_binding=rejection_binding,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )
        self.assertEqual(
            calibration_blocked["budgets"]["reserved"]["model_grade"] + 16,
            correction["imported_reserved"]["model_grade"],
        )
        self.assertEqual(
            calibration_blocked["budgets"]["observed"]["model_grade"] + 16,
            correction["imported_observed"]["model_grade"],
        )
        self.assertEqual(
            rejection_binding, correction["calibration_rejection_receipt"]
        )

    def test_partial_calibration_correction_shape_is_narrow(self) -> None:
        state = copy.deepcopy(self.fixture["campaign"])
        state["phase"] = "target_profile_ready"
        state["skill_evidence"][SKILL_IDS[0]]["grader_calibration"] = (
            self.fixture["bindings"]["host"]
        )
        self.assertTrue(_is_partial_calibration_correction(state))

        state["plans"].append({"role": "target_current"})
        self.assertFalse(_is_partial_calibration_correction(state))
        state["plans"].clear()
        state["skill_evidence"][SKILL_IDS[1]]["current_summary"] = (
            self.fixture["bindings"]["host"]
        )
        self.assertFalse(_is_partial_calibration_correction(state))

    def test_observed_host_projection_requires_exact_capability_and_result_set(
        self,
    ) -> None:
        provisional = json.loads(self.fixture["paths"]["host"].read_text())
        probe_set = json.loads(self.fixture["paths"]["probe_set"].read_text())
        terminal = self.fixture["bindings"]["host"]
        result = [{"probe_id": "force-load", "status": "pass", "terminal": terminal}]
        observed = project_observed_host(
            provisional,
            probe_set=probe_set,
            results=result,
            observed_manifest_path=self.fixture["campaign_root"] / "observed.json",
        )
        self.assertEqual(observed["capabilities"][0]["probe"]["status"], "pass")
        self.assertIn(
            str(self.fixture["campaign_root"] / "observed.json"),
            observed["command"]["argv"],
        )

        missing = copy.deepcopy(probe_set)
        missing["probes"][0]["capability"] = "multi_turn"
        missing = with_self_hash(missing, "probe_set_hash")
        with self.assertRaisesRegex(ContractError, "lacks probed capability"):
            project_observed_host(
                provisional,
                probe_set=missing,
                results=result,
                observed_manifest_path=self.fixture["campaign_root"] / "observed.json",
            )

    def test_qualification_projects_blocked_limited_and_qualified(self) -> None:
        blocked = self._blocked_qualification()
        self.assertEqual(blocked["decision"], "blocked")
        self.assertEqual(
            set(blocked["skills"]), set(self.fixture["campaign"]["product"]["skills"])
        )

        ready = materialize_bootstrap_evidence(self.fixture)
        limited = project_qualification(
            ready,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            observed_as_of="2026-08-03T00:00:00Z",
            valid_until="2026-08-04T00:00:00Z",
        )
        self.assertEqual(limited["decision"], "qualified_with_limits")
        self.assertEqual(
            [item["code"] for item in limited["limits"]], ["bootstrap-lineage"]
        )
        critical_unknown = copy.deepcopy(ready)
        critical_unknown["interaction_probes"]["requests"][0]["result_status"] = (
            "unknown"
        )
        critical_unknown = with_self_hash(critical_unknown, "campaign_hash")
        blocked_probe = project_qualification(
            critical_unknown,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            observed_as_of="2026-08-03T00:00:00Z",
            valid_until="2026-08-04T00:00:00Z",
        )
        self.assertEqual(blocked_probe["decision"], "blocked")
        self.assertIn(
            "critical-probe-not-pass",
            {item["code"] for item in blocked_probe["blockers"]},
        )

        comparison_path = write_json(
            self.fixture["campaign_root"] / "transition.json",
            closed_transition_report(),
        )
        comparison_binding = make_binding(
            comparison_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        ready["profiles"]["predecessor"] = {
            "cycle": self.fixture["bindings"]["host"],
            "host": self.fixture["bindings"]["host"],
            "product_hash": ready["product"]["plugin_tree"],
            "sentinel_hash": ready["sentinel_index"]["sha256"],
            "comparison_hash": closed_transition_report()["comparison_report_hash"],
            "qualification": None,
        }
        for skill_id in ready["skill_evidence"]:
            if skill_id in ready["product"]["skills"]:
                ready["skill_evidence"][skill_id]["transition_report"] = (
                    comparison_binding
                )
        ready = with_self_hash(ready, "campaign_hash")
        qualified = project_qualification(
            ready,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            observed_as_of="2026-08-03T00:00:00Z",
            valid_until="2026-08-04T00:00:00Z",
        )
        self.assertEqual(qualified["decision"], "qualified")

        inconsistent = copy.deepcopy(qualified)
        inconsistent["blockers"] = [
            {"code": "forced", "scope": "test", "evidence": None}
        ]
        inconsistent = with_self_hash(inconsistent, "qualification_hash")
        with self.assertRaisesRegex(ContractError, "decision differs"):
            validate_document(inconsistent, "qualification")

    def test_markdown_projection_is_deterministic(self) -> None:
        qualification = self._blocked_qualification()
        first = render_qualification_markdown(qualification)
        second = render_qualification_markdown(copy.deepcopy(qualification))
        self.assertEqual(first.encode(), second.encode())
        self.assertIn(qualification["qualification_hash"], first)

    def test_apparatus_gate_rejects_rehashed_failed_operation(self) -> None:
        ready = materialize_bootstrap_evidence(self.fixture)
        path = self.fixture["campaign_root"] / "apparatus-report.json"
        report = json.loads(path.read_text())
        report["operations"][0]["status"] = "fail"
        write_json(path, with_self_hash(report, "apparatus_report_hash"))
        ready["apparatus_report"] = make_binding(
            path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        ready = with_self_hash(ready, "campaign_hash")
        with self.assertRaisesRegex(ContractError, "operation status"):
            project_qualification(
                ready,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
                observed_as_of="2026-08-03T00:00:00Z",
                valid_until="2026-08-04T00:00:00Z",
            )

    def test_plugin_build_schema_and_release_identity_are_closed(self) -> None:
        build = json.loads(self.fixture["paths"]["bundle_build"].read_text())
        self.assertEqual(
            validate_bundle_build(build)["bundle_id"], "frontier-engineering/6.3.0"
        )
        build["release_build_id"] = "build-" + "0" * 24
        with self.assertRaisesRegex(ContractError, "release_build_id"):
            validate_bundle_build(build)


if __name__ == "__main__":
    unittest.main()
