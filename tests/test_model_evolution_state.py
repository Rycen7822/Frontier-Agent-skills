from __future__ import annotations

import argparse
import copy
import fcntl
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import _model_evolution_ops as operations  # noqa: E402
import _model_evolution_state as state_module  # noqa: E402
import model_evolution as controller  # noqa: E402
import support.model_evolution.repository as repository_support  # noqa: E402
from _model_evolution_campaign import validate_campaign  # noqa: E402
from _model_evolution_contract import (  # noqa: E402
    SKILL_IDS,
    ContractError,
    make_binding,
    validate_all_bindings,
    with_self_hash,
)
from _model_evolution_state import (  # noqa: E402
    CampaignStore,
    StateError,
    accept_candidate,
    advance_preflight,
    record_evidence,
    register_plan,
)
from support.model_evolution.documents import (  # noqa: E402
    analysis_summary,
    comparison_report,
)
from support.model_evolution.repository import (  # noqa: E402
    FIXED_COMMIT,
    FIXED_TREE,
    mark_probe_passed,
    materialize_apparatus_report,
    materialize_campaign,
    write_json,
)


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
    return comparison_report("revision")


class ModelEvolutionStateTest(unittest.TestCase):
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

    def test_probe_operation_lock_is_process_scoped_and_read_only(self) -> None:
        store = self.fixture["store"]
        original = store.path.read_bytes()
        self.assertFalse(store.probe_operation_running())
        with store.hold_probe_operation():
            self.assertTrue(store.probe_operation_running())
            with self.assertRaisesRegex(StateError, "already running"):
                with store.hold_probe_operation():
                    self.fail("concurrent probe operation unexpectedly acquired")
        self.assertFalse(store.probe_operation_running())
        self.assertEqual(original, store.path.read_bytes())

        store.probe_lock_path.unlink()
        store.read()
        self.assertEqual(original, store.path.read_bytes())
        with self.assertRaisesRegex(StateError, "lock is unavailable"):
            store.probe_operation_running()
        with self.assertRaisesRegex(StateError, "lock is unavailable"):
            with store.hold_probe_operation():
                self.fail("missing probe operation lock unexpectedly acquired")

    def test_create_accepts_only_declared_campaign_bootstrap_files(self) -> None:
        source_host = self.fixture["paths"]["host"]
        relative_host = Path(self.fixture["bindings"]["host"]["path"])
        source_build = self.fixture["paths"]["plugin_build"]
        relative_build = Path(self.fixture["bindings"]["plugin_build"]["path"])
        relative_plugin = Path(self.fixture["campaign"]["product"]["plugin_root"])
        relative_plugin /= ".codex-plugin/plugin.json"

        def seed(root: Path) -> tuple[Path, Path, Path]:
            targets = (
                (source_host, root / relative_host),
                (source_build, root / relative_build),
                (
                    self.fixture["paths"]["plugin_root"] / ".codex-plugin/plugin.json",
                    root / relative_plugin,
                ),
            )
            for source, target in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            return tuple(target for _, target in targets)

        accepted_root = Path(self.temporary.name) / "accepted-campaign"
        accepted_inputs = seed(accepted_root)
        accepted = CampaignStore(accepted_root, self.fixture["repository_root"])
        accepted.create(
            self.fixture["campaign"],
            bootstrap_paths=accepted_inputs,
        )
        self.assertTrue(accepted.path.is_file())
        self.assertTrue(accepted.lock_path.is_file())
        self.assertTrue(accepted.probe_lock_path.is_file())

        rejected_root = Path(self.temporary.name) / "rejected-campaign"
        rejected_inputs = seed(rejected_root)
        (rejected_root / "unbound.txt").write_text("unbound\n", encoding="utf-8")
        rejected = CampaignStore(rejected_root, self.fixture["repository_root"])
        with self.assertRaisesRegex(StateError, "undeclared bootstrap content"):
            rejected.create(
                self.fixture["campaign"],
                bootstrap_paths=rejected_inputs,
            )

    def test_frozen_sentinel_budget_counts_both_holdout_treatments(self) -> None:
        sentinel = json.loads(
            (
                REPOSITORY_ROOT / "evaluation/model-evolution/sentinel-index-v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            {
                "provider_requests": 246,
                "execute": 88,
                "model_grade": 152,
                "calibration": 64,
            },
            controller.qualification_request_ceilings(
                sentinel,
                repository_root=REPOSITORY_ROOT,
                campaign_root=REPOSITORY_ROOT,
                probe_count=6,
            ),
        )

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
                    "entries": [
                        {"execute_case_payload": {"subject_skill_id": SKILL_IDS[0]}}
                    ],
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
            "active_attempts": [],
            "recoverable_attempts": [],
            "execute_case_request_ceiling": 1,
            "model_grade_request_ceiling": 0,
            "worst_case_remaining_attempts": 1,
        }
        before = self.fixture["store"].path.read_bytes()
        wrong = json.loads(plan_path.read_text())
        wrong["entries"][0]["execute_case_payload"]["subject_skill_id"] = SKILL_IDS[1]
        wrong = with_self_hash(wrong, "plan_hash")
        wrong_path = write_json(
            self.fixture["campaign_root"] / "wrong-plan.json", wrong
        )
        wrong_args = copy.copy(args)
        wrong_args.plan = wrong_path
        host = json.loads(self.fixture["paths"]["host"].read_text())
        with (
            mock.patch.object(controller, "validate_current_plan", return_value=host),
            self.assertRaisesRegex(controller.CliError, "selected Skill"),
        ):
            controller._register_plan(wrong_args)
        self.assertEqual(before, self.fixture["store"].path.read_bytes())

        for field in ("indexed_attempts", "active_attempts", "recoverable_attempts"):
            blocked_value = 1 if field == "indexed_attempts" else [{"attempt": 1}]
            blocked = dict(status, **{field: blocked_value})
            with (
                mock.patch.object(
                    controller, "validate_current_plan", return_value=host
                ),
                self.subTest(field=field),
                mock.patch.object(controller, "runner_status", return_value=blocked),
            ):
                with self.assertRaisesRegex(controller.CliError, "requires zero"):
                    controller._register_plan(args)
            self.assertEqual(self.fixture["store"].path.read_bytes(), before)
        with (
            mock.patch.object(controller, "validate_current_plan", return_value=host),
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
            artifact=self.fixture["paths"]["plugin_build"],
            plugin_root=self.fixture["paths"]["plugin_root"],
        )
        with (
            mock.patch.object(
                controller,
                "git_identity",
                return_value={"commit": FIXED_COMMIT, "tree": FIXED_TREE},
            ),
            mock.patch.object(controller, "require_tracked_binding"),
            mock.patch.object(
                controller,
                "validate_plugin_staging",
                return_value=json.loads(
                    self.fixture["paths"]["plugin_build"].read_text()
                ),
            ),
            mock.patch.object(controller, "_emit"),
        ):
            controller._record(args)
        updated = self.fixture["store"].read()
        self.assertEqual(updated["phase"], "final_plugin_ready")
        self.assertEqual(
            updated["skill_evidence"]["plugin_build"],
            self.fixture["bindings"]["plugin_build"],
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
        summary = analysis_summary()
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

    def test_all_four_skill_calibrations_are_required_before_ready(self) -> None:
        state = self._prepared_state()
        binding = self.fixture["bindings"]["host"]
        graded_plan = plan_record(SKILL_IDS[0])
        graded_plan["model_grade_ceiling"] = 1
        with self.assertRaisesRegex(StateError, "requires all calibrations"):
            register_plan(state, graded_plan)
        for skill_id in SKILL_IDS[:-1]:
            record_evidence(
                state,
                role="grader_calibration",
                binding=binding,
                skill_id=skill_id,
            )
            self.assertEqual("target_profile_ready", state["phase"])
        last = SKILL_IDS[-1]
        record_evidence(
            state,
            role="grader_calibration",
            binding=binding,
            skill_id=last,
        )
        self.assertEqual("calibration_ready", state["phase"])
        self.assertTrue(
            all(
                state["skill_evidence"][skill_id]["grader_calibration"] == binding
                for skill_id in SKILL_IDS
            )
        )

    def test_no_candidate_and_candidate_state_chains_are_bounded(self) -> None:
        summary_path = write_json(
            self.fixture["campaign_root"] / "summary.json",
            analysis_summary(),
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
            binding=self.fixture["bindings"]["plugin_build"],
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
            "skills": copy.deepcopy(current["product"]["skills"]),
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
            binding=self.fixture["bindings"]["plugin_build"],
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
        validate_campaign(with_self_hash(candidate, "campaign_hash"))


class RepositoryFixtureBoundaryTest(unittest.TestCase):
    def test_campaign_fixture_needs_neither_bubblewrap_nor_real_skills(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            temporary = Path(raw)
            source_root = temporary / "product-inputs"
            for relative in (
                "bundle-manifest.json",
                "frontier-engineering.bundle.json",
                "evaluation/static-contract-diagnostic.json",
            ):
                target = source_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPOSITORY_ROOT / relative, target)
            with (
                mock.patch.object(repository_support, "SOURCE_ROOT", source_root),
                mock.patch("shutil.which", return_value=None),
            ):
                fixture = repository_support.materialize_campaign(
                    temporary / "fixture-root"
                )
            self.assertEqual(fixture["campaign"]["phase"], "declared")
            skill_files = sorted(
                fixture["paths"]["plugin_root"].glob("skills/*/SKILL.md")
            )
            self.assertEqual(len(skill_files), len(SKILL_IDS))
            self.assertTrue(
                all("Synthetic fixture." in path.read_text() for path in skill_files)
            )


if __name__ == "__main__":
    unittest.main()
