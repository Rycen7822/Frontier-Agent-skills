from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from _model_evolution_campaign import (  # noqa: E402
    prepare_predecessor,
    validate_campaign,
)
from _model_evolution_contract import (  # noqa: E402
    ContractError,
    evaluator_evidence_status,
    make_binding,
    resolve_binding,
    validate_bundle_build,
    validate_document,
    validate_formal_plan_timeouts,
    validate_formal_timeout_inputs,
    with_self_hash,
)
from _model_evolution_qualification import (  # noqa: E402
    project_observed_host,
    project_qualification,
    render_qualification_markdown,
    validate_qualification,
)
from support.model_evolution.documents import (  # noqa: E402
    analysis_summary,
    comparison_report,
)
from support.model_evolution.repository import (  # noqa: E402
    materialize_bootstrap_evidence,
    materialize_budget_approval,
    materialize_campaign,
    write_json,
)


def closed_transition_report() -> dict:
    return comparison_report("model_transition")


class ModelEvolutionDocumentsTest(unittest.TestCase):
    def test_formal_timeouts_preserve_host_cleanup_window(self) -> None:
        host = {"command": {"argv": ["host", "--timeout", "600"]}}
        spec = {"execution": {"timeout_seconds": 1230}}
        scenarios = [
            {"timeout_seconds": 630, "turns": [{}]},
            {"timeout_seconds": 1230, "turns": [{}, {}]},
        ]
        plan = {
            "entries": [
                {
                    "disposition": "execute",
                    "timeout_seconds": 630,
                    "execute_case_payload": {"turns": [{}]},
                },
                {
                    "disposition": "execute",
                    "timeout_seconds": 1230,
                    "execute_case_payload": {"turns": [{}, {}]},
                },
                {"disposition": "not_evaluable", "timeout_seconds": 1},
            ]
        }

        self.assertEqual(validate_formal_timeout_inputs(host, spec, scenarios), 1230)
        self.assertEqual(validate_formal_plan_timeouts(host, plan), 1230)
        spec["execution"]["timeout_seconds"] = 1229
        with self.assertRaisesRegex(ContractError, "at least 1230"):
            validate_formal_timeout_inputs(host, spec, scenarios)
        spec["execution"]["timeout_seconds"] = 1230
        scenarios[1]["timeout_seconds"] = 1229
        with self.assertRaisesRegex(ContractError, "at least 1230"):
            validate_formal_timeout_inputs(host, spec, scenarios)
        plan["entries"][1]["timeout_seconds"] = 1229
        with self.assertRaisesRegex(ContractError, "at least 1230"):
            validate_formal_plan_timeouts(host, plan)

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
        validators = {
            "campaign": validate_campaign,
            "qualification": validate_qualification,
        }
        for name, value in documents.items():
            with self.subTest(name=name):
                validator = validators.get(
                    name,
                    lambda document, document_name=name: validate_document(
                        document, document_name
                    ),
                )
                validator(value)
                tampered = copy.deepcopy(value)
                tampered[hash_fields[name]] = "sha256:" + "0" * 64
                with self.assertRaisesRegex(ContractError, "canonical content"):
                    validator(tampered)
                unknown = copy.deepcopy(value)
                unknown["unknown"] = True
                unknown = with_self_hash(unknown, hash_fields[name])
                with self.assertRaisesRegex(ContractError, "schema violation"):
                    validator(unknown)

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
            validate_campaign(campaign)

    def test_campaign_v2_is_fresh_and_rejects_supersession_state(self) -> None:
        campaign = self.fixture["campaign"]
        self.assertEqual(campaign["schema_version"], "model-evolution-campaign/2")
        self.assertEqual(
            campaign["budgets"]["reserved"],
            {field: 0 for field in campaign["budgets"]["ceiling"]},
        )

        superseding = copy.deepcopy(campaign)
        superseding["supersedes"] = None
        superseding = with_self_hash(superseding, "campaign_hash")
        with self.assertRaisesRegex(ContractError, "schema violation"):
            validate_campaign(superseding)

        legacy = copy.deepcopy(campaign)
        legacy["schema_version"] = "model-evolution-campaign/1"
        legacy = with_self_hash(legacy, "campaign_hash")
        with self.assertRaisesRegex(ContractError, "schema violation"):
            validate_campaign(legacy)

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
            analysis_summary(),
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
            validate_qualification(inconsistent)

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
            validate_bundle_build(build)["bundle_id"], "frontier-engineering/6.3.1"
        )
        build["release_build_id"] = "build-" + "0" * 24
        with self.assertRaisesRegex(ContractError, "release_build_id"):
            validate_bundle_build(build)


if __name__ == "__main__":
    unittest.main()
