from __future__ import annotations

import argparse
import copy
import io
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
import model_evolution as controller  # noqa: E402
from _model_evolution_contract import (  # noqa: E402
    SKILL_IDS,
    validate_document,
    with_self_hash,
)
from _model_evolution_qualification import validate_qualification  # noqa: E402
from _model_evolution_state import (  # noqa: E402
    StateError,
)
from support.model_evolution.host import materialize_campaign  # noqa: E402
from support.model_evolution.repository import (  # noqa: E402
    FIXED_COMMIT,
    FIXED_TREE,
    mark_probe_passed,
    materialize_apparatus_report,
    materialize_bootstrap_evidence,
    write_json,
)


class ModelEvolutionCliTest(unittest.TestCase):
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
        init_help = subprocess.run(
            [
                sys.executable,
                str(root / "scripts/model_evolution.py"),
                "--campaign-root",
                str(root / "campaign"),
                "init",
                "--help",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(init_help.returncode, 0, init_help.stderr)
        self.assertNotIn("supersed", init_help.stdout)
        self.assertFalse(any(root.rglob("__pycache__")))

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

        with (
            mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:7897"}),
            mock.patch.object(operations, "_run", side_effect=fake_run),
        ):
            fact = operations.verify_systemd_user("campaign", ["HTTP_PROXY"])
        self.assertEqual("systemd-user-lifecycle", fact["operation_id"])

        with (
            mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:7897"}),
            mock.patch.object(
                operations,
                "_run",
                side_effect=[
                    subprocess.CompletedProcess([], 0, "running\n", ""),
                    subprocess.CompletedProcess([], 0, "", ""),
                ],
            ),
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
        validate_qualification(json.loads(qualification.read_text()))
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
