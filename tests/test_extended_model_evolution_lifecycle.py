from __future__ import annotations

import argparse
import copy
import fcntl
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import _model_evolution_ops as operations  # noqa: E402
import _model_evolution_state as state_module  # noqa: E402
import model_evolution as controller  # noqa: E402
from _model_evolution_contract import (  # noqa: E402
    ContractError,
    SKILL_IDS,
    make_binding,
    validate_all_bindings,
    validate_document,
    with_self_hash,
)
from _model_evolution_state import (  # noqa: E402
    CampaignStore,
    StateError,
    accept_candidate,
    advance_preflight,
    record_evidence,
    register_plan,
    reserve_probes,
)
from model_evolution_test_support import (  # noqa: E402
    FIXED_COMMIT,
    FIXED_TREE,
    materialize_apparatus_report,
    materialize_bootstrap_evidence,
    materialize_campaign,
    mark_probe_passed,
    write_json,
)
from skill_evaluator_test_support import make_v5_schema_examples  # noqa: E402


def operation_fact(operation_id: str = "fixture-gate") -> dict:
    return {
        "operation_id": operation_id,
        "input_hash": "sha256:" + "3" * 64,
        "command_hash": "sha256:" + "4" * 64,
        "status": "pass",
        "duration_ms": 1,
    }


def plan_record(skill_id: str, role: str = "target_current") -> dict:
    return {
        "role": role,
        "skill_id": skill_id,
        "plan": {
            "root": "campaign",
            "path": "plan.json",
            "sha256": "sha256:" + "5" * 64,
        },
        "host_hash": "sha256:" + "6" * 64,
        "execute_ceiling": 1,
        "model_grade_ceiling": 0,
        "runner_status_hash": "sha256:" + "7" * 64,
    }


def closed_revision_report() -> dict:
    value = make_v5_schema_examples()["comparison-report-v1.schema.json"]
    value["authority_eligibility"] = "eligible"
    value["registration_status"] = "declared_pre_registered"
    value["result"]["status"] = "closed"
    return with_self_hash(value, "comparison_report_hash")


class ModelEvolutionLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = materialize_campaign(Path(self.temporary.name))

    def _write_state(self, state: dict) -> None:
        write_json(self.fixture["campaign_root"] / "campaign.json", state)

    def _prepared_state(self) -> dict:
        state = copy.deepcopy(self.fixture["campaign"])
        state["phase"] = "target_profile_ready"
        state["apparatus_report"] = materialize_apparatus_report(self.fixture)
        state["profiles"]["target_observed"] = self.fixture["bindings"]["host"]
        mark_probe_passed(state, self.fixture)
        return with_self_hash(state, "campaign_hash")

    def test_cas_lock_and_failed_replace_preserve_state_bytes(self) -> None:
        store = self.fixture["store"]
        apparatus = materialize_apparatus_report(self.fixture)
        original = store.path.read_bytes()
        with self.assertRaisesRegex(StateError, "undeclared bootstrap content"):
            store.create(self.fixture["campaign"])
        with self.assertRaisesRegex(StateError, "stale"):
            store.mutate(1, lambda state: advance_preflight(state, apparatus))
        self.assertEqual(store.path.read_bytes(), original)

        def fail_after_mutation(state: dict) -> None:
            state["phase"] = "apparatus_ready"
            raise RuntimeError("fixture interruption")

        with self.assertRaisesRegex(RuntimeError, "interruption"):
            store.mutate(0, fail_after_mutation)
        self.assertEqual(store.path.read_bytes(), original)

        with store.lock_path.open("r+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(StateError, "lock is held"):
                store.mutate(0, lambda state: advance_preflight(state, apparatus))
        self.assertEqual(store.path.read_bytes(), original)

        with mock.patch.object(
            state_module.os, "replace", side_effect=OSError("interrupted")
        ):
            with self.assertRaisesRegex(OSError, "interrupted"):
                store.mutate(0, lambda state: advance_preflight(state, apparatus))
        self.assertEqual(store.path.read_bytes(), original)
        self.assertFalse(list(store.root.glob(".campaign.json.*.tmp")))

    def test_create_accepts_only_declared_campaign_bootstrap_files(self) -> None:
        source_host = self.fixture["paths"]["host"]
        relative_host = Path(self.fixture["bindings"]["host"]["path"])

        accepted_root = Path(self.temporary.name) / "accepted-campaign"
        accepted_host = accepted_root / relative_host
        accepted_host.parent.mkdir(parents=True)
        accepted_host.write_bytes(source_host.read_bytes())
        accepted = CampaignStore(accepted_root, self.fixture["repository_root"])
        accepted.create(
            self.fixture["campaign"],
            bootstrap_paths=(accepted_host,),
        )
        self.assertTrue(accepted.path.is_file())

        rejected_root = Path(self.temporary.name) / "rejected-campaign"
        rejected_host = rejected_root / relative_host
        rejected_host.parent.mkdir(parents=True)
        rejected_host.write_bytes(source_host.read_bytes())
        (rejected_root / "unbound.txt").write_text("unbound\n", encoding="utf-8")
        rejected = CampaignStore(rejected_root, self.fixture["repository_root"])
        with self.assertRaisesRegex(StateError, "undeclared bootstrap content"):
            rejected.create(
                self.fixture["campaign"],
                bootstrap_paths=(rejected_host,),
            )

    def test_unsigned_and_dirty_git_identity_are_rejected(self) -> None:
        repository = Path(self.temporary.name) / "unsigned-repository"
        repository.mkdir()
        commands = (
            ["git", "init", "-q"],
            ["git", "config", "user.name", "Fixture"],
            ["git", "config", "user.email", "fixture@example.invalid"],
        )
        for command in commands:
            subprocess.run(command, cwd=repository, check=True, capture_output=True)
        tracked = repository / "tracked.txt"
        tracked.write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--no-gpg-sign", "-m", "fixture"],
            cwd=repository,
            check=True,
        )
        with self.assertRaises(operations.OperationError):
            operations.git_identity(repository)
        tracked.write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(operations.OperationError, "not clean"):
            operations.git_identity(repository)

    def test_repository_binding_can_fall_back_only_to_frozen_git_blob(self) -> None:
        repository = Path(self.temporary.name) / "blob-repository"
        campaign_root = repository / ".work/campaign"
        campaign_root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Fixture"], cwd=repository, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.invalid"],
            cwd=repository,
            check=True,
        )
        source = repository / "bundle.json"
        source.write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "bundle.json"], cwd=repository, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--no-gpg-sign", "-m", "base"],
            cwd=repository,
            check=True,
        )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        binding = make_binding(
            source,
            root="repository",
            repository_root=repository,
            campaign_root=campaign_root,
        )
        source.write_text("candidate\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "hash differs"):
            validate_all_bindings(binding, repository, campaign_root)
        validate_all_bindings(
            binding,
            repository,
            campaign_root,
            lambda path, expected_hash: operations.git_blob_matches(
                repository, revision, path, expected_hash
            ),
        )
        source.unlink()
        source.symlink_to(repository / "outside")
        with self.assertRaisesRegex(ContractError, "symlinked"):
            validate_all_bindings(
                binding,
                repository,
                campaign_root,
                lambda path, expected_hash: operations.git_blob_matches(
                    repository, revision, path, expected_hash
                ),
            )

        source_manifest = self.fixture["paths"]["bundle_manifest"]
        source_manifest.write_text("candidate bytes\n", encoding="utf-8")
        expected = self.fixture["bindings"]["bundle_manifest"]

        def frozen_match(revision: str, path: str, expected_hash: str) -> bool:
            return (
                revision == FIXED_COMMIT
                and path == expected["path"]
                and expected_hash == expected["sha256"]
            )

        store = CampaignStore(
            self.fixture["campaign_root"],
            self.fixture["repository_root"],
            repository_blob_matches=frozen_match,
        )
        self.assertEqual(store.read()["campaign_id"], "campaign-fixture")
        updated = store.mutate(0, lambda state: None)
        self.assertEqual(updated["state_revision"], 1)

    def test_candidate_version_release_note_and_file_mode_contract(self) -> None:
        repository = Path(self.temporary.name) / "candidate-repository"
        repository.mkdir()
        for command in (
            ["git", "init", "-q"],
            ["git", "config", "user.name", "Fixture"],
            ["git", "config", "user.email", "fixture@example.invalid"],
        ):
            subprocess.run(command, cwd=repository, check=True, capture_output=True)
        manifest = json.loads((REPOSITORY_ROOT / "bundle-manifest.json").read_text())
        write_json(repository / "bundle-manifest.json", manifest)
        write_json(repository / "frontier-engineering.bundle.json", {"build": "base"})
        write_json(
            repository / "evaluation/static-contract-diagnostic.json",
            {"static": "base"},
        )
        (repository / "RELEASE_NOTES.md").write_text(
            "# Release notes\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--no-gpg-sign", "-m", "base"],
            cwd=repository,
            check=True,
        )
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        owner = SKILL_IDS[0]
        for row in manifest["skills"]:
            if row["id"] == owner:
                row["version"] = "1.1.0"
        write_json(repository / "bundle-manifest.json", manifest)
        write_json(
            repository / "frontier-engineering.bundle.json", {"build": "candidate"}
        )
        write_json(
            repository / "evaluation/static-contract-diagnostic.json",
            {"static": "candidate"},
        )
        (repository / "RELEASE_NOTES.md").write_text(
            "# Release notes\n\n- rc-1 long-document-segmented-writing 1.1.0\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repository, check=True)
        subprocess.run(
            ["git", "commit", "-q", "--no-gpg-sign", "-m", "candidate"],
            cwd=repository,
            check=True,
        )
        candidate = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        changed = [
            "RELEASE_NOTES.md",
            "bundle-manifest.json",
            "evaluation/static-contract-diagnostic.json",
            "frontier-engineering.bundle.json",
        ]
        self.assertEqual(
            operations._validate_candidate_version(
                repository,
                base_commit=base,
                candidate_commit=candidate,
                owner_surface=owner,
                root_cause_ids=["rc-1"],
                changed_paths=changed,
            ),
            "1.1.0",
        )
        with self.assertRaisesRegex(operations.OperationError, "mode or type"):
            operations._validate_candidate_file_modes(
                ":100644 100755 0000000 1111111 M\tchanged.py"
            )

    def test_existing_evaluator_fake_chain_and_systemd_argv_are_reused(self) -> None:
        facts = operations.fake_full_chain(REPOSITORY_ROOT)
        self.assertEqual(
            [fact["operation_id"] for fact in facts],
            [
                "fake-compile",
                "fake-runner-status",
                "fake-runner",
                "fake-analyze",
                "fake-bootstrap-comparison",
            ],
        )
        argv = operations.systemd_probe_argv(
            "frontier-campaign-fixture-preflight",
            self.fixture["campaign_root"] / "closed",
        )
        self.assertEqual(
            argv[:5],
            [
                "systemd-run",
                "--user",
                "--unit",
                "frontier-campaign-fixture-preflight",
                "--collect",
            ],
        )

    def test_probe_closes_once_and_partial_reservation_never_resends(self) -> None:
        store = self.fixture["store"]
        apparatus = materialize_apparatus_report(self.fixture)
        store.mutate(0, lambda state: advance_preflight(state, apparatus))
        approval = write_json(
            self.fixture["campaign_root"] / "budget-approval.json", {"approved": True}
        )
        with mock.patch.object(controller, "_emit"):
            controller._probe(
                argparse.Namespace(
                    repository_root=self.fixture["repository_root"],
                    campaign_root=self.fixture["campaign_root"],
                    expected_revision=1,
                    budget_approval=approval,
                )
            )
        state = store.read()
        self.assertEqual(
            (state["phase"], state["state_revision"]), ("target_profile_ready", 3)
        )
        calls = self.fixture["repository_root"] / "fixtures/fake-codex.calls.jsonl"
        self.assertEqual(len(calls.read_text().splitlines()), 1)

        second_root = Path(self.temporary.name) / "second"
        partial = materialize_campaign(second_root)
        partial_apparatus = materialize_apparatus_report(partial)
        partial["store"].mutate(
            0, lambda state: advance_preflight(state, partial_apparatus)
        )
        partial["store"].mutate(
            1,
            lambda state: reserve_probes(state, ["force-load"]),
        )
        partial_approval = write_json(
            partial["campaign_root"] / "approval.json", {"approved": True}
        )
        with self.assertRaisesRegex(
            operations.OperationError, "automatic resend is forbidden"
        ):
            controller._probe(
                argparse.Namespace(
                    repository_root=partial["repository_root"],
                    campaign_root=partial["campaign_root"],
                    expected_revision=2,
                    budget_approval=partial_approval,
                )
            )
        self.assertFalse(
            (partial["repository_root"] / "fixtures/fake-codex.calls.jsonl").exists()
        )
        self.assertIsNone(
            partial["store"].read()["budgets"]["observed"]["provider_requests"]
        )

    def test_complete_probe_terminals_resume_without_provider_resend(self) -> None:
        store = self.fixture["store"]
        apparatus = materialize_apparatus_report(self.fixture)
        store.mutate(0, lambda state: advance_preflight(state, apparatus))
        probe_set = json.loads(self.fixture["paths"]["probe_set"].read_text())
        reserved = store.mutate(
            1,
            lambda state: reserve_probes(
                state, [row["probe_id"] for row in probe_set["probes"]]
            ),
        )
        approval = write_json(
            self.fixture["campaign_root"] / "approval.json", {"approved": True}
        )
        approval_binding = make_binding(
            approval,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        first = operations.run_interaction_probes(
            reserved,
            probe_set=probe_set,
            approval_binding=approval_binding,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        calls = self.fixture["repository_root"] / "fixtures/fake-codex.calls.jsonl"
        call_count = len(calls.read_text().splitlines())
        second = operations.run_interaction_probes(
            reserved,
            probe_set=probe_set,
            approval_binding=approval_binding,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            resume_existing=True,
        )
        self.assertEqual(first, second)
        self.assertEqual(call_count, len(calls.read_text().splitlines()))

    def test_probe_diagnostic_stops_remaining_rows(self) -> None:
        campaign = copy.deepcopy(self.fixture["campaign"])
        campaign["phase"] = "apparatus_ready"
        campaign["interaction_probes"]["requests"] = [
            {
                "request_id": f"request-{index}",
                "probe_id": "force-load",
                "status": "reserved",
                "artifact": None,
                "result_status": None,
            }
            for index in (1, 2)
        ]
        probe_set = json.loads(self.fixture["paths"]["probe_set"].read_text())
        failure = operations.OperationError("protocol diagnostic")
        with mock.patch.object(
            operations, "_run_probe_process", side_effect=failure
        ) as run:
            with self.assertRaisesRegex(
                operations.OperationError, "protocol diagnostic"
            ):
                operations.run_interaction_probes(
                    campaign,
                    probe_set=probe_set,
                    approval_binding=self.fixture["bindings"]["host"],
                    repository_root=self.fixture["repository_root"],
                    campaign_root=self.fixture["campaign_root"],
                )
        self.assertEqual(run.call_count, 1)

        blocked_root = Path(self.temporary.name) / "blocked-probe"
        blocked = materialize_campaign(blocked_root)
        blocked_apparatus = materialize_apparatus_report(blocked)
        blocked["store"].mutate(
            0, lambda state: advance_preflight(state, blocked_apparatus)
        )
        approval = write_json(
            blocked["campaign_root"] / "approval.json", {"approved": True}
        )
        with mock.patch.object(
            controller,
            "run_interaction_probes",
            side_effect=operations.OperationError("fixture protocol failure"),
        ):
            with self.assertRaisesRegex(
                operations.OperationError, "fixture protocol failure"
            ):
                controller._probe(
                    argparse.Namespace(
                        repository_root=blocked["repository_root"],
                        campaign_root=blocked["campaign_root"],
                        expected_revision=1,
                        budget_approval=approval,
                    )
                )
        failed = blocked["store"].read()
        self.assertEqual(failed["state_revision"], 3)
        self.assertEqual(
            failed["interaction_probes"]["blocker"], "fixture protocol failure"
        )
        projection = state_module.status_projection(
            failed,
            plan_statuses=[],
            blockers=[
                {"code": "interaction-probe", "message": "fixture protocol failure"}
            ],
            runner_commands=[],
        )
        self.assertIsNone(projection["next_event"])

    def test_plan_registration_rejects_existing_attempt_without_mutation(self) -> None:
        state = self._prepared_state()
        self._write_state(state)
        plan_path = write_json(
            self.fixture["campaign_root"] / "plan.json",
            with_self_hash(
                {
                    "host_manifest_hash": json.loads(
                        self.fixture["paths"]["host"].read_text()
                    )["manifest_hash"],
                    "package_hashes": {
                        SKILL_IDS[0]: state["product"]["skills"][SKILL_IDS[0]][
                            "root_hash"
                        ]
                    },
                    "artifacts": {"root": "artifacts", "index_relpath": "index.jsonl"},
                },
                "plan_hash",
            ),
        )
        args = argparse.Namespace(
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            expected_revision=0,
            role="target_current",
            skill_id=SKILL_IDS[0],
            plan=plan_path,
        )
        status = {
            "indexed_attempts": 0,
            "active_attempts": 0,
            "recoverable_attempts": 0,
            "execute_case_request_ceiling": 1,
            "model_grade_request_ceiling": 0,
            "worst_case_remaining_attempts": 1,
        }
        before = self.fixture["store"].path.read_bytes()
        for field in ("indexed_attempts", "active_attempts", "recoverable_attempts"):
            blocked = dict(status, **{field: 1})
            with (
                self.subTest(field=field),
                mock.patch.object(controller, "runner_status", return_value=blocked),
            ):
                with self.assertRaisesRegex(controller.CliError, "requires zero"):
                    controller._register_plan(args)
            self.assertEqual(self.fixture["store"].path.read_bytes(), before)
        with (
            mock.patch.object(controller, "runner_status", return_value=status),
            mock.patch.object(controller, "_emit"),
        ):
            controller._register_plan(args)
        updated = self.fixture["store"].read()
        self.assertEqual(updated["budgets"]["reserved"]["provider_requests"], 1)

    def test_plugin_build_record_binds_selected_signed_identity(self) -> None:
        state = self._prepared_state()
        state["phase"] = "decision_ready"
        state = with_self_hash(state, "campaign_hash")
        self._write_state(state)
        args = argparse.Namespace(
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            expected_revision=0,
            role="plugin_build",
            skill_id=None,
            artifact=self.fixture["paths"]["bundle_build"],
        )
        with (
            mock.patch.object(
                controller,
                "git_identity",
                return_value={"commit": FIXED_COMMIT, "tree": FIXED_TREE},
            ),
            mock.patch.object(controller, "require_tracked_binding"),
            mock.patch.object(controller, "_emit"),
        ):
            controller._record(args)
        updated = self.fixture["store"].read()
        self.assertEqual(updated["phase"], "final_plugin_ready")
        self.assertEqual(
            updated["skill_evidence"]["plugin_build"],
            self.fixture["bindings"]["bundle_build"],
        )

    def test_summary_and_comparison_evidence_join_selected_inputs(self) -> None:
        campaign = self._prepared_state()
        host_hash = json.loads(self.fixture["paths"]["host"].read_text())[
            "manifest_hash"
        ]
        plan = with_self_hash(
            {
                "host_manifest_hash": host_hash,
                "package_hashes": {SKILL_IDS[0]: "sha256:" + "8" * 64},
                "artifacts": {"root": "artifacts", "index_relpath": "index.jsonl"},
            },
            "plan_hash",
        )
        plan_path = write_json(self.fixture["campaign_root"] / "joined-plan.json", plan)
        plan_binding = make_binding(
            plan_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        campaign["plans"].append(
            {
                **plan_record(SKILL_IDS[0]),
                "plan": plan_binding,
                "host_hash": host_hash,
            }
        )
        summary = make_v5_schema_examples()["analysis-summary-v4.schema.json"]
        summary["plan_hash"] = plan["plan_hash"]
        summary["host_manifest_hash"] = host_hash
        summary = with_self_hash(summary, "summary_hash")
        controller._validate_evidence_join(
            campaign,
            role="current_summary",
            skill_id=SKILL_IDS[0],
            value=summary,
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        wrong = copy.deepcopy(summary)
        wrong["plan_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(controller.CliError, "registered plan"):
            controller._validate_evidence_join(
                campaign,
                role="current_summary",
                skill_id=SKILL_IDS[0],
                value=wrong,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

        summary_path = write_json(
            self.fixture["campaign_root"] / "joined-summary.json", summary
        )
        campaign["skill_evidence"][SKILL_IDS[0]]["current_summary"] = make_binding(
            summary_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        with self.assertRaisesRegex(controller.CliError, "selected summaries"):
            controller._validate_evidence_join(
                campaign,
                role="transition_report",
                skill_id=SKILL_IDS[0],
                value={"inputs": []},
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
            )

    def test_no_candidate_and_candidate_state_chains_are_bounded(self) -> None:
        summary_path = write_json(
            self.fixture["campaign_root"] / "summary.json",
            with_self_hash(
                make_v5_schema_examples()["analysis-summary-v4.schema.json"],
                "summary_hash",
            ),
        )
        revision_path = write_json(
            self.fixture["campaign_root"] / "revision.json", closed_revision_report()
        )
        summary = make_binding(
            summary_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )
        revision = make_binding(
            revision_path,
            root="campaign",
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
        )

        current = self._prepared_state()
        exhausted = copy.deepcopy(current)
        exhausted["budgets"]["ceiling"]["provider_requests"] = 1
        register_plan(exhausted, plan_record(SKILL_IDS[0]))
        with self.assertRaisesRegex(StateError, "ceiling exceeded"):
            register_plan(exhausted, plan_record(SKILL_IDS[1]))
        for skill_id in SKILL_IDS:
            register_plan(current, plan_record(skill_id))
        for skill_id in SKILL_IDS:
            record_evidence(
                current, role="current_summary", binding=summary, skill_id=skill_id
            )
        self.assertEqual(current["phase"], "decision_ready")
        no_candidate = copy.deepcopy(current)
        record_evidence(
            no_candidate,
            role="plugin_build",
            binding=self.fixture["bindings"]["bundle_build"],
            skill_id=None,
        )
        for skill_id in SKILL_IDS:
            register_plan(no_candidate, plan_record(skill_id, "target_holdout"))
            record_evidence(
                no_candidate, role="holdout_summary", binding=summary, skill_id=skill_id
            )
        self.assertEqual(no_candidate["phase"], "holdout_ready")

        candidate = copy.deepcopy(current)
        candidate_record = {
            "base_commit": FIXED_COMMIT,
            "candidate_commit": "9" * 40,
            "candidate_tree": "a" * 40,
            "changed_paths": [f"{SKILL_IDS[0]}/SKILL.md"],
            "root_cause_ids": ["rc-1"],
            "owner_surface": SKILL_IDS[0],
            "semantic_changes": ["Restore one bounded behavior."],
            "operations": [operation_fact()],
        }
        accept_candidate(candidate, candidate_record)
        with self.assertRaisesRegex(StateError, "only legal"):
            accept_candidate(candidate, candidate_record)
        for skill_id in SKILL_IDS:
            register_plan(candidate, plan_record(skill_id, "target_candidate"))
            record_evidence(
                candidate, role="candidate_summary", binding=summary, skill_id=skill_id
            )
            record_evidence(
                candidate, role="revision_report", binding=revision, skill_id=skill_id
            )
        self.assertEqual(candidate["phase"], "candidate_evidence_ready")
        record_evidence(
            candidate,
            role="plugin_build",
            binding=self.fixture["bindings"]["bundle_build"],
            skill_id=None,
        )
        for skill_id in SKILL_IDS:
            register_plan(candidate, plan_record(skill_id, "target_holdout"))
            record_evidence(
                candidate,
                role="holdout_summary",
                binding=summary,
                skill_id=skill_id,
            )
        self.assertEqual(candidate["phase"], "holdout_ready")
        validate_document(with_self_hash(candidate, "campaign_hash"), "campaign")

    def test_candidate_path_policy_rejects_controller_and_accepts_bound_fixture(
        self,
    ) -> None:
        campaign = self._prepared_state()
        campaign["phase"] = "decision_ready"
        sentinel = json.loads(self.fixture["paths"]["sentinel"].read_text())

        def git_output(_root: Path, *args: str, **_kwargs: object) -> str:
            if args[:2] == ("rev-parse", "HEAD"):
                return "9" * 40
            if args and args[0] == "diff" and "--summary" in args:
                return ""
            if args and args[0] == "diff" and "--name-status" in args:
                return "M\tscripts/model_evolution.py"
            return ""

        with (
            mock.patch.object(
                operations,
                "git_identity",
                return_value={"commit": "9" * 40, "tree": "a" * 40},
            ),
            mock.patch.object(operations, "_git", side_effect=git_output),
        ):
            with self.assertRaisesRegex(operations.OperationError, "non-owner path"):
                operations.candidate_source(
                    repository_root=self.fixture["repository_root"],
                    campaign=campaign,
                    sentinel=sentinel,
                    base_commit=FIXED_COMMIT,
                    candidate_commit="9" * 40,
                    owner_surface=SKILL_IDS[0],
                    root_cause_ids=["rc-1"],
                    semantic_changes=["bounded change"],
                )

    def test_qualification_publish_verify_status_and_immutability(self) -> None:
        ready = materialize_bootstrap_evidence(self.fixture)
        self._write_state(ready)
        orphan = self.fixture["campaign_root"] / ".qualification.tmp-0"
        orphan.mkdir()
        (orphan / "partial").write_text("interrupted", encoding="utf-8")
        args = argparse.Namespace(
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            expected_revision=0,
            observed_as_of="2026-08-03T00:00:00Z",
            valid_until="2026-08-04T00:00:00Z",
        )
        with mock.patch.object(controller, "_emit"):
            controller._qualify(args)
        self.assertFalse(orphan.exists())
        qualification = (
            self.fixture["campaign_root"] / "qualification/qualification.json"
        )
        validate_document(json.loads(qualification.read_text()), "qualification")
        with self.assertRaisesRegex(StateError, "already exists"):
            with mock.patch.object(controller, "_emit"):
                controller._qualify(args)
        with self.assertRaisesRegex(StateError, "immutable"):
            self.fixture["store"].mutate(0, lambda state: None)

        command = [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts/model_evolution.py"),
            "--repository-root",
            str(self.fixture["repository_root"]),
            "--campaign-root",
            str(self.fixture["campaign_root"]),
            "verify",
        ]
        verified = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["verified"])

        status_args = argparse.Namespace(
            repository_root=self.fixture["repository_root"],
            campaign_root=self.fixture["campaign_root"],
            json=True,
        )
        before = {
            path.relative_to(self.fixture["campaign_root"]): path.read_bytes()
            for path in self.fixture["campaign_root"].rglob("*")
            if path.is_file()
        }
        outputs = []
        with mock.patch.object(
            controller,
            "git_identity",
            return_value={"commit": FIXED_COMMIT, "tree": FIXED_TREE},
        ):
            for _ in range(2):
                raw = io.BytesIO()
                stream = io.TextIOWrapper(raw, encoding="utf-8")
                with mock.patch("sys.stdout", stream):
                    controller._status(status_args)
                    stream.flush()
                outputs.append(raw.getvalue().decode())
                stream.detach()
        after = {
            path.relative_to(self.fixture["campaign_root"]): path.read_bytes()
            for path in self.fixture["campaign_root"].rglob("*")
            if path.is_file()
        }
        self.assertEqual(outputs[0].encode(), outputs[1].encode())
        self.assertEqual(before, after)
        self.assertEqual(json.loads(outputs[0])["next_event"], "qualification_complete")
        markdown = self.fixture["campaign_root"] / "qualification/qualification.md"
        markdown.write_text("tampered\n", encoding="utf-8")
        with mock.patch.object(
            controller,
            "git_identity",
            return_value={"commit": FIXED_COMMIT, "tree": FIXED_TREE},
        ):
            raw = io.BytesIO()
            stream = io.TextIOWrapper(raw, encoding="utf-8")
            with mock.patch("sys.stdout", stream):
                controller._status(status_args)
                stream.flush()
            invalid = json.loads(raw.getvalue().decode())
            stream.detach()
        self.assertIsNone(invalid["next_event"])
        self.assertIn(
            "qualification-invalid", {item["code"] for item in invalid["blockers"]}
        )
        self.assertEqual(
            {path.name for path in self.fixture["campaign_root"].iterdir()},
            {
                ".campaign.lock",
                "apparatus-report.json",
                "campaign.json",
                "inputs",
                "qualification",
                "summary.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
