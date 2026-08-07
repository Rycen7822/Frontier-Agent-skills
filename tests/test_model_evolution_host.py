from __future__ import annotations

import argparse
import copy
import json
import os
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
import build_model_evolution_host as host_builder  # noqa: E402
import model_evolution as controller  # noqa: E402
from _codex_eval_delivery import MODEL_EVOLUTION_ENV_ALLOWLIST  # noqa: E402
from _model_evolution_contract import (  # noqa: E402
    make_binding,
    with_self_hash,
)
from _model_evolution_state import (  # noqa: E402
    CampaignStore,
    advance_preflight,
    reserve_probes,
)
from support.model_evolution.host import materialize_campaign  # noqa: E402
from support.model_evolution.repository import (  # noqa: E402
    FIXED_COMMIT,
    FIXED_TREE,
    materialize_apparatus_report,
    materialize_budget_approval,
    write_json,
)


class ModelEvolutionHostTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = materialize_campaign(Path(self.temporary.name))

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
            with self.assertRaisesRegex(controller.CliError, "fresh campaign"):
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
                ("code-mode-host-hash", "tool schema identity differs"),
                ("transport-env", "transport environment differs"),
            )
            for mutation, message in mutations:
                invalid_host = copy.deepcopy(valid_host)
                if mutation == "skill-root":
                    invalid_host["catalog"]["entries"][0]["root_hash"] = (
                        "sha256:" + "0" * 64
                    )
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
                elif mutation == "code-mode-host-hash":
                    position = invalid_host["command"]["argv"].index(
                        "--code-mode-host-sha256"
                    )
                    invalid_host["command"]["argv"][position + 1] = (
                        "sha256:" + "0" * 64
                    )
                else:
                    invalid_host["command"]["env_allowlist"] = []
                write_json(host, with_self_hash(invalid_host, "manifest_hash"))
                with (
                    self.subTest(mutation=mutation),
                    self.assertRaisesRegex(
                        operations.OperationError,
                        message,
                    ),
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
        self.assertEqual(state["schema_version"], "model-evolution-campaign/2")
        self.assertNotIn("supersedes", state)

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
        runtime.write_text(
            "#!/bin/sh\nprintf 'codex-cli 0.146.1\\n'\n", encoding="utf-8"
        )
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
        builder_evidence = json.loads(self.fixture["paths"]["plugin_build"].read_text())
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
                built["command"]["argv"][
                    built["command"]["argv"].index("--code-mode-host-sha256") + 1
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
        blocked = partial["store"].read()
        self.assertIsNotNone(blocked["interaction_probes"]["blocker"])
        retry_approval = materialize_budget_approval(
            partial,
            blocked,
            "retry-approval.json",
        )
        before_retry = partial["store"].path.read_bytes()
        with (
            mock.patch.object(controller, "run_interaction_probes") as provider,
            self.assertRaisesRegex(controller.CliError, "not recoverable"),
        ):
            controller._probe(
                argparse.Namespace(
                    repository_root=partial["repository_root"],
                    campaign_root=partial["campaign_root"],
                    expected_revision=blocked["state_revision"],
                    budget_approval=retry_approval,
                )
            )
        provider.assert_not_called()
        self.assertEqual(before_retry, partial["store"].path.read_bytes())

    def test_concurrent_probe_exits_without_state_or_provider_change(self) -> None:
        probe_set = json.loads(
            (
                REPOSITORY_ROOT
                / "evaluation/model-evolution/codex-interaction-probes-v1.json"
            ).read_text()
        )
        probe_ids = [row["probe_id"] for row in probe_set["probes"]]
        terminal_counts = sorted({0, 1, len(probe_ids) // 2, len(probe_ids)})
        for terminal_count in terminal_counts:
            with self.subTest(terminal_count=terminal_count):
                fixture = materialize_campaign(
                    Path(self.temporary.name) / f"concurrent-{terminal_count}"
                )
                store = fixture["store"]
                apparatus = materialize_apparatus_report(fixture)
                store.mutate(0, lambda state: advance_preflight(state, apparatus))
                reserved = store.mutate(
                    1, lambda state: reserve_probes(state, probe_ids)
                )
                approval = materialize_budget_approval(fixture, reserved)
                probes = fixture["campaign_root"] / "probes"
                probes.mkdir()
                for request in reserved["interaction_probes"]["requests"][
                    :terminal_count
                ]:
                    write_json(
                        probes / f"{request['request_id']}.json",
                        {"request_id": request["request_id"]},
                    )
                args = argparse.Namespace(
                    repository_root=fixture["repository_root"],
                    campaign_root=fixture["campaign_root"],
                    expected_revision=2,
                    budget_approval=approval,
                )
                before = {
                    path.relative_to(store.root): path.read_bytes()
                    for path in store.root.rglob("*")
                    if path.is_file()
                }
                with (
                    store.hold_probe_operation(),
                    mock.patch.object(
                        controller, "run_interaction_probes"
                    ) as provider,
                ):
                    with self.assertRaisesRegex(
                        state_module.StateError,
                        "probe operation is already running",
                    ):
                        controller._probe(args)
                after = {
                    path.relative_to(store.root): path.read_bytes()
                    for path in store.root.rglob("*")
                    if path.is_file()
                }
                provider.assert_not_called()
                self.assertEqual(before, after)

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
        approval = materialize_budget_approval(self.fixture, reserved)
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
        self.assertEqual(len(probe_set["probes"]), len(first["statuses"]))
        with (
            mock.patch.object(
                operations,
                "_run_probe_process",
                side_effect=AssertionError("resume resent a provider request"),
            ),
            mock.patch.object(controller, "_emit"),
        ):
            controller._probe(
                argparse.Namespace(
                    repository_root=self.fixture["repository_root"],
                    campaign_root=self.fixture["campaign_root"],
                    expected_revision=2,
                    budget_approval=approval,
                )
            )
        closed = store.read()
        self.assertEqual("target_profile_ready", closed["phase"])
        self.assertEqual(3, closed["state_revision"])

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
            mock.patch.object(
                operations.subprocess, "Popen", return_value=process
            ) as popen,
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
            probe_running=False,
            probe_command=None,
        )
        self.assertIsNone(projection["next_event"])


if __name__ == "__main__":
    unittest.main()
