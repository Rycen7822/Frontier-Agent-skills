from __future__ import annotations

import argparse
import copy
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

import _model_evolution_ops as operations  # noqa: E402
import _model_evolution_state as state_module  # noqa: E402
import build_model_evolution_host as host_builder  # noqa: E402
import model_evolution as controller  # noqa: E402
from _codex_eval_delivery import MODEL_EVOLUTION_ENV_ALLOWLIST  # noqa: E402
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
    materialize_budget_approval,
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

    def test_cli_import_does_not_create_source_bytecode(self) -> None:
        root = Path(self.temporary.name) / "cli-source"
        for relative in ("scripts", "skill-evaluator/scripts"):
            shutil.copytree(
                REPOSITORY_ROOT / relative,
                root / relative,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        environment = os.environ.copy()
        environment.pop("PYTHONDONTWRITEBYTECODE", None)
        result = subprocess.run(
            [sys.executable, str(root / "scripts/model_evolution.py"), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(root.rglob("__pycache__")))

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

        rejected_root = Path(self.temporary.name) / "rejected-campaign"
        rejected_inputs = seed(rejected_root)
        (rejected_root / "unbound.txt").write_text("unbound\n", encoding="utf-8")
        rejected = CampaignStore(rejected_root, self.fixture["repository_root"])
        with self.assertRaisesRegex(StateError, "undeclared bootstrap content"):
            rejected.create(
                self.fixture["campaign"],
                bootstrap_paths=rejected_inputs,
            )

    def test_init_binds_exact_campaign_host_and_plugin_staging(self) -> None:
        campaign_root = Path(self.temporary.name) / "controller-init"
        inputs = campaign_root / "inputs"
        inputs.mkdir(parents=True)
        host = inputs / "target-provisional-host.json"
        plugin_build = inputs / "plugin-build-evidence.json"
        shutil.copyfile(self.fixture["paths"]["host"], host)
        shutil.copyfile(self.fixture["paths"]["plugin_build"], plugin_build)
        plugin_root = campaign_root / "staging/frontier-engineering-plugin"
        shutil.copytree(self.fixture["paths"]["plugin_root"], plugin_root)
        rebound_host = json.loads(host.read_text())
        argv = rebound_host["command"]["argv"]
        argv[argv.index("--host-manifest") + 1] = str(host)
        argv[argv.index("--plugin-root") + 1] = str(plugin_root)
        write_json(host, with_self_hash(rebound_host, "manifest_hash"))
        args = argparse.Namespace(
            repository_root=self.fixture["repository_root"],
            campaign_root=campaign_root,
            campaign_id="controller-init-fixture",
            plugin_root=plugin_root,
            plugin_build_evidence=plugin_build,
            target_host=host,
            probe_set=self.fixture["paths"]["probe_set"],
            sentinel_index=self.fixture["paths"]["sentinel"],
            predecessor_cycle=None,
            predecessor_host=None,
            predecessor_comparison=None,
            predecessor_qualification=None,
            supersedes=None,
            supersession_failure_receipt=None,
            supersession_calibration_rejection_receipt=None,
            provider_request_ceiling=81,
            execute_ceiling=38,
            model_grade_ceiling=42,
            artifact_byte_ceiling=1_073_741_824,
            download_byte_ceiling=0,
            candidate_ceiling=1,
            reviewer_ceiling=0,
            optimizer_ceiling=0,
        )
        evidence = json.loads(plugin_build.read_text())
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
                return_value=evidence,
            ),
            mock.patch.object(controller, "_emit"),
        ):
            invalid_args = copy.copy(args)
            invalid_args.provider_request_ceiling -= 1
            with self.assertRaisesRegex(controller.CliError, "worst-case"):
                controller._init(invalid_args)
            self.assertFalse((campaign_root / "campaign.json").exists())
            valid_host = json.loads(host.read_text())
            mutations = (
                ("skill-root", "plugin Skill bytes differ"),
                ("catalog", "catalog hash differs"),
                ("adapter", "adapter identity differs"),
                ("source-commit", "repository identity differs"),
                ("source-tree", "repository identity differs"),
                ("source-path", "repository identity differs"),
                ("host-path", "command binding is invalid"),
                ("transport-env", "transport environment differs"),
            )
            for mutation, message in mutations:
                invalid_host = copy.deepcopy(valid_host)
                if mutation == "skill-root":
                    invalid_host["catalog"]["entries"][0]["root_hash"] = "sha256:" + "0" * 64
                elif mutation == "catalog":
                    invalid_host["catalog"]["catalog_hash"] = "sha256:" + "0" * 64
                elif mutation == "adapter":
                    invalid_host["identity"]["adapter"]["sha256"] = "sha256:" + "0" * 64
                elif mutation == "source-commit":
                    invalid_host["identity"]["repository"]["revision"] = "0" * 40
                elif mutation == "source-tree":
                    invalid_host["identity"]["repository"]["tree"] = "0" * 40
                elif mutation == "source-path":
                    invalid_host["identity"]["repository"]["worktree"] = "/wrong"
                elif mutation == "host-path":
                    position = invalid_host["command"]["argv"].index("--host-manifest")
                    invalid_host["command"]["argv"][position + 1] = "/missing"
                else:
                    invalid_host["command"]["env_allowlist"] = []
                write_json(host, with_self_hash(invalid_host, "manifest_hash"))
                with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    operations.OperationError,
                    message,
                ):
                    controller._init(args)
                self.assertFalse((campaign_root / "campaign.json").exists())
            write_json(host, valid_host)
            controller._init(args)
        state = CampaignStore(
            campaign_root,
            self.fixture["repository_root"],
        ).read()
        self.assertEqual("campaign", state["product"]["plugin_build"]["root"])
        self.assertEqual(
            "staging/frontier-engineering-plugin",
            state["product"]["plugin_root"],
        )
        self.assertEqual(evidence["plugin_tree_hash"], state["product"]["plugin_tree"])

    def test_cumulative_request_ceilings_charge_prior_failures_once(self) -> None:
        request_ceilings = {
            "provider_requests": 246,
            "execute": 88,
            "model_grade": 152,
            "calibration": 64,
        }
        supersedes = {
            "imported_reserved": {
                "provider_requests": 126,
                "execute": 48,
                "model_grade": 96,
            },
            "imported_observed": {
                "provider_requests": 100,
                "execute": 40,
                "model_grade": 80,
            },
        }
        self.assertEqual(
            {
                "provider_requests": 308,
                "execute": 136,
                "model_grade": 184,
            },
            controller._cumulative_request_ceilings(
                request_ceilings,
                supersedes,
            ),
        )
        self.assertEqual(
            {
                "provider_requests": 372,
                "execute": 136,
                "model_grade": 248,
            },
            controller._cumulative_request_ceilings(
                request_ceilings,
                supersedes,
                reuse_calibration_reservation=False,
            ),
        )
        supersedes["imported_observed"]["model_grade"] = 120
        self.assertEqual(
            208,
            controller._cumulative_request_ceilings(
                request_ceilings,
                supersedes,
            )["model_grade"],
        )

    def test_frozen_sentinel_budget_counts_both_holdout_treatments(self) -> None:
        sentinel = json.loads(
            (
                REPOSITORY_ROOT
                / "evaluation/model-evolution/sentinel-index-v1.json"
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
        base_owner_version = next(
            row["version"] for row in manifest["skills"] if row["id"] == owner
        )
        major, minor, _patch = map(int, base_owner_version.split("."))
        candidate_owner_version = f"{major}.{minor + 1}.0"
        for row in manifest["skills"]:
            if row["id"] == owner:
                row["version"] = candidate_owner_version
        write_json(repository / "bundle-manifest.json", manifest)
        write_json(
            repository / "frontier-engineering.bundle.json", {"build": "candidate"}
        )
        write_json(
            repository / "evaluation/static-contract-diagnostic.json",
            {"static": "candidate"},
        )
        (repository / "RELEASE_NOTES.md").write_text(
            f"# Release notes\n\n- rc-1 {owner} {candidate_owner_version}\n",
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
            candidate_owner_version,
        )
        with self.assertRaisesRegex(operations.OperationError, "mode or type"):
            operations._validate_candidate_file_modes(
                ":100644 100755 0000000 1111111 M\tchanged.py"
            )

    def test_existing_evaluator_fake_chain_and_systemd_argv_are_reused(self) -> None:
        self.assertIn(
            operations.PLUGIN_BUILD_GATE_SCRIPT,
            operations.ALLOWED_GATE_SCRIPTS,
        )
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
        resumed = operations.render_runner_command(
            self.fixture["campaign_root"] / "plan.json",
            self.fixture["campaign_root"] / "index.jsonl",
            attempt_budget=3,
            service_id="frontier-resume",
            repository_root=REPOSITORY_ROOT,
            resume=True,
        )
        self.assertIn(" --resume --new-attempt-budget 3", resumed)

    def test_systemd_preflight_requires_matching_allowlisted_environment(self) -> None:
        def fake_run(argv, **_kwargs):
            if argv[-1] == "is-system-running":
                stdout = "running\n"
            elif argv[-1] == "show-environment":
                stdout = "HTTP_PROXY=http://127.0.0.1:7897\n"
            else:
                Path(argv[-1]).write_text("closed", encoding="utf-8")
                stdout = ""
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        with mock.patch.dict(
            os.environ, {"HTTP_PROXY": "http://127.0.0.1:7897"}
        ), mock.patch.object(operations, "_run", side_effect=fake_run):
            fact = operations.verify_systemd_user("campaign", ["HTTP_PROXY"])
        self.assertEqual("systemd-user-lifecycle", fact["operation_id"])

        with mock.patch.dict(
            os.environ, {"HTTP_PROXY": "http://127.0.0.1:7897"}
        ), mock.patch.object(
            operations,
            "_run",
            side_effect=[
                subprocess.CompletedProcess([], 0, "running\n", ""),
                subprocess.CompletedProcess([], 0, "", ""),
            ],
        ):
            with self.assertRaisesRegex(
                operations.OperationError, "differs for HTTP_PROXY"
            ):
                operations.verify_systemd_user("campaign", ["HTTP_PROXY"])

    def test_preflight_schema_fixtures_match_their_live_contracts(self) -> None:
        campaign = self.fixture["store"].read()
        hash_fields = {
            "budget_approval": "approval_hash",
            "campaign": "campaign_hash",
            "interaction_probes": "probe_set_hash",
            "sentinel_index": "sentinel_hash",
        }
        for name, hash_field in hash_fields.items():
            fixture = with_self_hash(
                operations._minimal_schema_fixture(name, campaign),
                hash_field,
            )
            validate_document(fixture, name)

    def test_preflight_binds_the_exact_staged_plugin_catalog(self) -> None:
        host = json.loads(self.fixture["paths"]["host"].read_text())
        plugin_root = self.fixture["paths"]["plugin_root"]
        operations._validate_host_plugin_binding(host, plugin_root)

        stale_catalog = copy.deepcopy(host)
        stale_catalog["catalog"]["catalog_hash"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(
            operations.OperationError,
            "catalog hash differs",
        ):
            operations._validate_host_plugin_binding(stale_catalog, plugin_root)

        host["command"]["argv"].extend(["--plugin-root", str(plugin_root)])
        with self.assertRaisesRegex(
            operations.OperationError,
            "does not bind one plugin root",
        ):
            operations._validate_host_plugin_binding(host, plugin_root)

    def test_host_builder_resolves_native_codex_and_catalog_identity(self) -> None:
        root = Path(self.temporary.name) / "codex-package"
        entrypoint = root / "bin/codex.js"
        runtime = (
            root
            / "node_modules/@openai/codex-linux-x64"
            / "vendor/x86_64-unknown-linux-musl/bin/codex"
        )
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("// fixture entrypoint\n", encoding="utf-8")
        write_json(root / "package.json", {"version": "0.146.1"})
        runtime.parent.mkdir(parents=True)
        runtime.write_text("#!/bin/sh\nprintf 'codex-cli 0.146.1\\n'\n", encoding="utf-8")
        runtime.chmod(0o700)
        selected = {"display_name": "Luna", "slug": "gpt-5.6-luna"}
        home = Path(self.temporary.name) / "home"
        write_json(
            home / ".codex/models_cache.json",
            {"client_version": "0.146.1", "models": [selected]},
        )

        with (
            mock.patch.object(host_builder.sys, "platform", "linux"),
            mock.patch.object(host_builder.platform, "machine", return_value="x86_64"),
            mock.patch.object(host_builder.Path, "home", return_value=home),
        ):
            resolved, version = host_builder._codex_runtime(entrypoint)
            revision = host_builder._model_revision("gpt-5.6-luna", version)

        self.assertEqual(runtime.resolve(), resolved)
        self.assertEqual("0.146.1", version)
        self.assertEqual(
            "codex-catalog-0.146.1-"
            + host_builder._hash_bytes(host_builder._canonical_bytes(selected)),
            revision,
        )

    def test_host_builder_replaces_all_derived_identity_before_init(self) -> None:
        template = json.loads(self.fixture["paths"]["host"].read_text())
        codex_argv = template["command"]["argv"]
        codex_path = Path(codex_argv[codex_argv.index("--codex") + 1]).resolve()
        template["command"]["env_allowlist"] = []
        template["catalog"]["entries"][0]["root_hash"] = "sha256:" + "0" * 64
        template["catalog"]["catalog_hash"] = "sha256:" + "0" * 64
        template["identity"]["execution"]["catalog_hash"] = "sha256:" + "0" * 64
        template["identity"]["execution"]["skill_hash"] = "sha256:" + "0" * 64
        template["identity"]["adapter"]["sha256"] = "sha256:" + "0" * 64
        template["identity"]["host_version"] = "0.0.0"
        template["identity"]["execution"]["harness"] = "stale-harness"
        template["identity"]["execution"]["model_revision"] = "stale-catalog"
        probe_path = "codex-interaction-probes-v1.json"
        template["reset"]["probe"]["artifact"]["path"] = probe_path
        for capability in template["capabilities"]:
            capability["probe"]["artifact"]["path"] = probe_path
        template_path = write_json(
            Path(self.temporary.name) / "stale-host-template.json",
            template,
        )
        builder_evidence = json.loads(
            self.fixture["paths"]["plugin_build"].read_text()
        )
        builder_evidence["skill_versions"] = {
            entry["id"]: entry["version"] for entry in template["catalog"]["entries"]
        }
        builder_evidence_path = write_json(
            Path(self.temporary.name) / "builder-evidence.json",
            builder_evidence,
        )
        output = Path(
            os.path.relpath(
                Path(self.temporary.name) / "built-host.json",
                Path.cwd(),
            )
        )
        scripts_target = self.fixture["repository_root"] / "scripts"
        scripts_target.mkdir()
        for name in host_builder.codex_eval_host.ADAPTER_SOURCE_FILES:
            shutil.copyfile(REPOSITORY_ROOT / "scripts" / name, scripts_target / name)
        identity = {
            "dirty": False,
            "revision": FIXED_COMMIT,
            "tree": FIXED_TREE,
            "worktree": str(self.fixture["repository_root"]),
        }
        with (
            mock.patch.object(
                host_builder,
                "_codex_runtime",
                return_value=(codex_path, "0.146.1"),
            ),
            mock.patch.object(
                host_builder,
                "_model_revision",
                return_value="codex-catalog-0.146.1-sha256:" + "3" * 64,
            ),
            mock.patch.object(
                host_builder,
                "_repository_identity",
                return_value=identity,
            ),
        ):
            built = host_builder.build_host(
                repository_root=self.fixture["repository_root"],
                template_path=template_path,
                plugin_root=self.fixture["paths"]["plugin_root"],
                plugin_build_path=builder_evidence_path,
                output_path=output,
                manifest_id="built-host-fixture",
                session_id="built-host-session",
            )
        self.assertEqual(
            list(MODEL_EVOLUTION_ENV_ALLOWLIST),
            built["command"]["env_allowlist"],
        )
        self.assertEqual(
            host_builder.codex_eval_host.ADAPTER_VERSION,
            built["identity"]["adapter"]["version"],
        )
        self.assertEqual("0.146.1", built["identity"]["host_version"])
        self.assertEqual(
            "codex-cli-0.146.1-effort-high-profile-fixture-profile-tier-default",
            built["identity"]["execution"]["harness"],
        )
        self.assertEqual(
            "codex-catalog-0.146.1-sha256:" + "3" * 64,
            built["identity"]["execution"]["model_revision"],
        )
        self.assertEqual(
            host_builder.codex_eval_host.adapter_source_hash(scripts_target),
            built["identity"]["adapter"]["sha256"],
        )
        self.assertEqual(
            host_builder.isolated_tool_schema_hash(
                built["command"]["argv"][
                    built["command"]["argv"].index("--codex-sha256") + 1
                ],
                built["command"]["argv"][
                    built["command"]["argv"].index("--isolation-tool-sha256") + 1
                ],
            ),
            built["identity"]["execution"]["tool_schema_hash"],
        )
        self.assertEqual(identity, built["identity"]["repository"])
        operations.validate_target_host_staging(
            output,
            self.fixture["paths"]["plugin_root"],
            repository_root=self.fixture["repository_root"],
            expected_commit=FIXED_COMMIT,
            expected_tree=FIXED_TREE,
        )
        original = output.read_bytes()
        with (
            mock.patch.object(
                host_builder,
                "_codex_runtime",
                return_value=(codex_path, "0.146.1"),
            ),
            mock.patch.object(
                host_builder,
                "_model_revision",
                return_value="codex-catalog-0.146.1-sha256:" + "3" * 64,
            ),
            mock.patch.object(
                host_builder,
                "_repository_identity",
                return_value=identity,
            ),
            self.assertRaisesRegex(host_builder.HostBuildError, "refusing to replace"),
        ):
            host_builder.build_host(
                repository_root=self.fixture["repository_root"],
                template_path=template_path,
                plugin_root=self.fixture["paths"]["plugin_root"],
                plugin_build_path=builder_evidence_path,
                output_path=output,
                manifest_id="built-host-fixture",
                session_id="built-host-session",
            )
        self.assertEqual(original, output.read_bytes())

    def test_probe_closes_once_and_partial_reservation_never_resends(self) -> None:
        store = self.fixture["store"]
        apparatus = materialize_apparatus_report(self.fixture)
        store.mutate(0, lambda state: advance_preflight(state, apparatus))
        approval = materialize_budget_approval(
            self.fixture,
            store.read(),
        )
        invalid_approval = json.loads(approval.read_text())
        invalid_approval["campaign_hash"] = "sha256:" + "0" * 64
        invalid_approval = with_self_hash(invalid_approval, "approval_hash")
        invalid_path = write_json(
            self.fixture["campaign_root"] / "invalid-budget-approval.json",
            invalid_approval,
        )
        with self.assertRaisesRegex(controller.CliError, "campaign_hash differs"):
            controller._probe(
                argparse.Namespace(
                    repository_root=self.fixture["repository_root"],
                    campaign_root=self.fixture["campaign_root"],
                    expected_revision=1,
                    budget_approval=invalid_path,
                )
            )
        self.assertEqual(1, store.read()["state_revision"])
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
        self.assertEqual(
            1,
            len(list((self.fixture["campaign_root"] / "probes").glob("*.json"))),
        )

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
        partial_approval = materialize_budget_approval(
            partial,
            partial["store"].read(),
            "approval.json",
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
        self.assertFalse((partial["campaign_root"] / "probes").exists())
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
        with mock.patch.object(
            operations,
            "_run_probe_process",
            side_effect=AssertionError("resume resent a provider request"),
        ):
            second = operations.run_interaction_probes(
                reserved,
                probe_set=probe_set,
                approval_binding=approval_binding,
                repository_root=self.fixture["repository_root"],
                campaign_root=self.fixture["campaign_root"],
                resume_existing=True,
            )
        self.assertEqual(first, second)

    def test_probe_outer_timeout_has_grace_and_kills_owned_process_group(self) -> None:
        self.assertEqual(
            35.0,
            operations._probe_process_timeout(["host", "--timeout", "5"]),
        )
        for argv in (
            ["host"],
            ["host", "--timeout", "nan"],
            ["host", "--timeout", "0"],
        ):
            with self.assertRaisesRegex(
                operations.OperationError, "target Host timeout is invalid"
            ):
                operations._probe_process_timeout(argv)

        process = mock.Mock(pid=4321)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="host", timeout=0.1),
            ("", "bounded diagnostic"),
        ]
        with (
            mock.patch.object(operations.subprocess, "Popen", return_value=process) as popen,
            mock.patch.object(operations.os, "killpg") as killpg,
            self.assertRaisesRegex(
                operations.OperationError,
                "outer timeout after 0.1s: bounded diagnostic",
            ),
        ):
            operations._run_probe_process(
                ["host", "--timeout", "5"],
                {
                    "probe_id": "force-load",
                    "capability": "force_load",
                    "prompt": "fixture prompt",
                    "required_observations": [],
                },
                environment={},
                workspace=self.fixture["repository_root"],
                timeout=0.1,
            )
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(4321, operations.signal.SIGKILL)
        self.assertEqual(2, process.communicate.call_count)

    def test_unknown_critical_probe_closes_terminals_without_advancing(self) -> None:
        store = self.fixture["store"]
        apparatus = materialize_apparatus_report(self.fixture)
        store.mutate(0, lambda state: advance_preflight(state, apparatus))
        approval = materialize_budget_approval(self.fixture, store.read())

        def unknown_outcome(campaign, **_kwargs):
            request_id = campaign["interaction_probes"]["requests"][0]["request_id"]
            return {
                "artifacts": {request_id: self.fixture["bindings"]["host"]},
                "statuses": {request_id: "unknown"},
                "results_binding": self.fixture["bindings"]["host"],
                "observed_host_binding": self.fixture["bindings"]["host"],
            }

        with (
            mock.patch.object(
                controller,
                "run_interaction_probes",
                side_effect=unknown_outcome,
            ),
            self.assertRaisesRegex(controller.CliError, "force_load"),
        ):
            controller._probe(
                argparse.Namespace(
                    repository_root=self.fixture["repository_root"],
                    campaign_root=self.fixture["campaign_root"],
                    expected_revision=1,
                    budget_approval=approval,
                )
            )
        state = store.read()
        self.assertEqual("apparatus_ready", state["phase"])
        self.assertIn("force_load", state["interaction_probes"]["blocker"])
        self.assertEqual(1, state["budgets"]["observed"]["provider_requests"])

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
        approval = materialize_budget_approval(
            blocked,
            blocked["store"].read(),
            "approval.json",
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

    def test_status_projection_counts_runner_attempt_arrays(self) -> None:
        projection = state_module.status_projection(
            self.fixture["store"].read(),
            plan_statuses=[
                {
                    "active_attempts": [{"attempt": 1}, {"attempt": 2}],
                    "recoverable_attempts": [{"attempt": 3}],
                },
                {
                    "active_attempts": [],
                    "recoverable_attempts": [
                        {"attempt": 4},
                        {"attempt": 5},
                    ],
                },
            ],
            blockers=[],
            runner_commands=[],
        )
        self.assertEqual(2, projection["active_attempts"])
        self.assertEqual(3, projection["recoverable_attempts"])

        blocked = state_module.status_projection(
            self.fixture["store"].read(),
            plan_statuses=[
                {
                    "role": "target_current",
                    "skill_id": "skill-evaluator",
                    "active_attempts": [],
                    "recoverable_attempts": [],
                    "invalid_attempts": 1,
                }
            ],
            blockers=[],
            runner_commands=["must-not-run"],
        )
        self.assertIsNone(blocked["next_event"])
        self.assertEqual([], blocked["runner_commands"])
        self.assertEqual("plan-invalid", blocked["blockers"][0]["code"])

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
                        {
                            "execute_case_payload": {
                                "subject_skill_id": SKILL_IDS[0]
                            }
                        }
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
        wrong_path = write_json(self.fixture["campaign_root"] / "wrong-plan.json", wrong)
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
        self.assertTrue(all(
            state["skill_evidence"][skill_id]["grader_calibration"] == binding
            for skill_id in SKILL_IDS
        ))

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
                "staging",
                "summary.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
