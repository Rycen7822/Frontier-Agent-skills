from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "card_cycle.py"
SCHEMA = ROOT / "schemas" / "card-protocol.schema.json"
REGISTRY = ROOT / "registries" / "artifact-family-contracts.json"
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"
HANDOFF_SCHEMA = ROOT / "schemas" / "plan-execution-handoff.schema.json"
SCRIPT_DIRECTORY = ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
SPEC = importlib.util.spec_from_file_location("wp_card_cycle_under_test", CLI)
assert SPEC is not None and SPEC.loader is not None
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


def _run_private_child_mode() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "--bounded-git-child":
        return
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if sys.argv[2] == "flood":
        chunk = b"x" * 65_536
        while True:
            os.write(1, chunk)
            os.write(2, chunk)
    if sys.argv[2] == "close":
        os.close(1)
        os.close(2)
        while True:
            time.sleep(60)
    if sys.argv[2] == "stderr":
        os.write(2, b"unexpected stderr")
        raise SystemExit(0)
    raise SystemExit(2)


_run_private_child_mode()


class BoundedGitObserverTests(unittest.TestCase):
    @staticmethod
    def _repository(parent: Path) -> Path:
        source = parent / "repo"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "wp@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "WP"], check=True)
        (source / "input.txt").write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "input.txt"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "fixture"], check=True)
        return source

    def test_repository_fence_uses_exact_eight_sanitized_git_children(self) -> None:
        real_popen = subprocess.Popen
        calls: list[list[str]] = []

        def spy(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
            calls.append(argv)
            self.assertEqual(cycle.GIT_ENV, kwargs["env"])
            self.assertEqual(subprocess.DEVNULL, kwargs["stdin"])
            self.assertEqual(["git", "--no-pager"], argv[:2])
            self.assertEqual(["-c", "core.fsmonitor=false", "-c", "diff.external="], argv[4:8])
            return real_popen(argv, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            source = self._repository(Path(directory))
            with mock.patch.object(cycle.subprocess, "Popen", side_effect=spy):
                observation = cycle._capture_program_source(source)
        self.assertEqual("repository", observation["kind"])
        self.assertEqual(8, len(calls))
        self.assertEqual(2, sum(argv[8:10] == ["rev-parse", "HEAD^{commit}"] for argv in calls))
        self.assertEqual(2, sum(argv[8:10] == ["ls-files", "-v"] for argv in calls))
        self.assertEqual(2, sum(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))

    def test_unversioned_publication_uses_four_python_observations_and_no_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "input.txt").write_text("stable\n", encoding="utf-8")
            with mock.patch.object(cycle, "_source_observation", wraps=cycle._source_observation) as observer:
                with mock.patch.object(cycle.subprocess, "Popen", side_effect=AssertionError("unexpected Git child")):
                    kind, session, _ = cycle._open_publication_capture(source)
                    (source / "plan.md").write_text("projection\n", encoding="utf-8")
                    cycle._publication_fence(kind, session)
            self.assertEqual(4, observer.call_count)

    def test_exact_safe_status_config_values_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._repository(Path(directory))
            for key, value in (
                ("core.fileMode", "true"), ("core.ignoreStat", "false"),
                ("core.trustCtime", "true"), ("core.checkStat", "default"),
            ):
                subprocess.run(["git", "-C", str(source), "config", key, value], check=True)
            self.assertEqual("repository", cycle._capture_program_source(source)["kind"])

    def test_post_publish_failure_preserves_final_and_retry_converges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "input.txt").write_text("stable\n", encoding="utf-8")
            kind, session, before = cycle._open_publication_capture(source)
            target = source / "plan.md"
            cycle._publish_immutable(source, target.name, b"projection\n")
            with mock.patch.object(
                cycle, "_source_observation",
                side_effect=cycle.CycleError("E_SOURCE_UNAVAILABLE", "test cap", exit_code=5),
            ):
                with self.assertRaisesRegex(cycle.CycleError, "source could not be verified") as raised:
                    cycle._publication_fence(kind, session)
            self.assertEqual("E_POST_PUBLISH_UNVERIFIED", raised.exception.code)
            self.assertEqual(b"projection\n", target.read_bytes())
            cycle._publish_immutable(source, target.name, b"projection\n")
            after = cycle._publication_fence(kind, session)
            _, transition = cycle._publication_transition(before, after, target.name)
            self.assertEqual([{"path": "plan.md", "status": "added"}], transition["changed_paths"])

    def test_dangerous_repository_config_and_index_flags_fail_before_status(self) -> None:
        variants = (
            ("FiLtEr.Mixed.Process", "unsafe-command"),
            ("core.worktree", "../other"),
            ("core.attributesFile", "../attributes"),
            ("core.excludesFile", "../excludes"),
            ("extensions.worktreeConfig", "true"),
            ("core.fileMode", "false"),
            ("core.ignoreStat", "true"),
            ("core.trustCtime", "false"),
            ("core.checkStat", "minimal"),
        )
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            for index, (key, value) in enumerate(variants):
                with self.subTest(key=key):
                    case_root = parent / str(index)
                    case_root.mkdir()
                    source = self._repository(case_root)
                    subprocess.run(["git", "-C", str(source), "config", key, value], check=True)
                    calls: list[list[str]] = []

                    def spy(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
                        calls.append(argv)
                        return real_popen(argv, **kwargs)

                    with mock.patch.object(cycle.subprocess, "Popen", side_effect=spy):
                        with self.assertRaises(cycle.CycleError):
                            cycle._capture_program_source(source)
                    self.assertFalse(any(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))

            flagged_root = parent / "flagged"
            flagged_root.mkdir()
            flagged = self._repository(flagged_root)
            subprocess.run(["git", "-C", str(flagged), "update-index", "--skip-worktree", "input.txt"], check=True)
            calls = []
            with mock.patch.object(cycle.subprocess, "Popen", side_effect=lambda argv, **kwargs: (calls.append(argv), real_popen(argv, **kwargs))[1]):
                with self.assertRaises(cycle.CycleError):
                    cycle._capture_program_source(flagged)
            self.assertFalse(any(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))
            nested_root = parent / "nested"
            nested_root.mkdir()
            repository = self._repository(nested_root)
            nested = repository / "child"
            nested.mkdir()
            calls = []
            with mock.patch.object(cycle.subprocess, "Popen", side_effect=lambda argv, **kwargs: (calls.append(argv), real_popen(argv, **kwargs))[1]):
                with self.assertRaises(cycle.CycleError):
                    cycle._capture_program_source(nested)
            self.assertFalse(any(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))
        with self.assertRaises(cycle.CycleError):
            cycle._parse_index(b"H 100644 " + b"0" * 40 + b" 2\tconflict.txt\0")

    def test_bounded_runner_drains_both_pipes_and_reaps_uncooperative_children(self) -> None:
        real_popen = subprocess.Popen
        fixed_prefix: list[str] | None = None
        for mode in ("flood", "close", "stderr"):
            with self.subTest(mode=mode):
                def factory(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
                    nonlocal fixed_prefix
                    fixed_prefix = argv[:8]
                    return real_popen(
                        [sys.executable, str(Path(__file__).resolve()), "--bounded-git-child", mode],
                        stdin=kwargs["stdin"], stdout=kwargs["stdout"], stderr=kwargs["stderr"],
                        env={**kwargs["env"], "PYTHONDONTWRITEBYTECODE": "1"}, close_fds=True,
                    )

                started = time.monotonic()
                with mock.patch.object(cycle.subprocess, "Popen", side_effect=factory):
                    with self.assertRaises(cycle.CycleError):
                        cycle._bounded_git(
                            Path("/tmp"), ("status",), stdout_cap=1_024,
                            deadline=time.monotonic() + 0.4,
                        )
                self.assertLess(time.monotonic() - started, 2.4)
                self.assertEqual(
                    ["git", "--no-pager", "-C", "/tmp", "-c", "core.fsmonitor=false", "-c", "diff.external="],
                    fixed_prefix,
                )


class BriefCardCycleTests(unittest.TestCase):
    FAMILY_ARTIFACTS = {
        "plan-delta": {"design-decision", "migration-plan", "outcome-slices"},
        "evidence": {"spike-evidence"},
        "brief": {"plan-brief"},
        "handoff": {"plan-handoff"},
        "program": {"plan-program"},
        "output-projection": {"output-projection"},
        "context-capsule": {"context-capsule"},
        "long-document-handoff": {"long-document-handoff"},
    }

    def _run(
        self,
        subcommand: str,
        command: dict[str, object],
        source_root: Path,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        self.assertTrue(CLI.is_file(), "target card_cycle.py entrypoint is absent")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        arguments = [
            sys.executable,
            str(CLI),
            subcommand,
            "--fields-json",
            json.dumps(command.get("fields"), ensure_ascii=False, separators=(",", ":")),
            "--source-root",
            str(source_root),
        ]
        if command.get("contract_id") == "wp.route.resume/2":
            arguments.append("--resume")
        if "outcome" in command:
            arguments.extend([
                "--outcome-json",
                json.dumps(command["outcome"], ensure_ascii=False, separators=(",", ":")),
            ])
        arguments.extend(extra)
        previous = command.get("previous_receipt") if subcommand != "route" else None
        return subprocess.run(
            arguments,
            input=(
                json.dumps(previous, ensure_ascii=False, separators=(",", ":"))
                if subcommand != "route"
                else None
            ),
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def _receipt(self, completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("", completed.stderr)
        self.assertEqual(1, len(completed.stdout.splitlines()))
        self.assertLessEqual(len(completed.stdout.encode("utf-8")), 12_288)
        return json.loads(completed.stdout)

    @staticmethod
    def _route_command() -> dict[str, object]:
        return {
            "contract_id": "wp.route.initial/2",
            "invocation_phase": "initial",
            "previous_receipt": None,
            "fields": {
                "explicit_plan_request": True,
                "root_cause_status": "known",
                "intent_status": "defined",
                "copy_paste_projection_requested": False,
                "disposable_spike": False,
                "durable_handoff": False,
                "external_side_effect": False,
                "independent_write_slices": 1,
                "long_corpus_only": False,
                "migration_or_rollback": False,
                "public_contract": False,
                "resume_required": False,
                "same_session_execution": True,
                "strategy_family_count": 1,
            },
            "outcome": {"blocker": None},
        }

    def test_route_help_and_all_card_input_contracts_are_compact_and_exact(self) -> None:
        outputs = []
        for columns in ("20", "200"):
            env = {**os.environ, "LC_ALL": "C", "COLUMNS": columns, "PYTHONDONTWRITEBYTECODE": "1"}
            completed = subprocess.run([sys.executable, str(CLI), "route", "--help"], text=True, capture_output=True, check=False, env=env)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("", completed.stderr)
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertLessEqual(len(outputs[0].encode("utf-8")), 1_024)
        lines = outputs[0].splitlines()
        self.assertEqual("usage: card_cycle.py route --fields-json JSON --source-root PATH [--resume --work-root PATH]", lines[0])
        initial = json.loads(lines[1].removeprefix("initial_input_contract="))
        self.assertEqual("wp.route.initial/2", initial["contract_id"])
        self.assertEqual({"contract_id", "required_fields", "required_root_args"}, set(initial))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "subject.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            self._receipt(self._run("route", self._route_command(), source))
        groups = initial["required_fields"]
        projected = [name for group in (groups["boolean"], groups["string_array"], groups["integer_min"], groups["enum"]) for name in group]
        schema, registry, manifest = cycle._load_contracts()
        self.assertEqual(sorted(schema["$defs"]["routeFields"]["required"]), sorted(projected))
        self.assertEqual(len(projected), len(set(projected)))

        direct = {
            "wp.profiles.brief", "wp.profiles.handoff", "wp.profiles.program",
            "wp.experiments.disposable-spike", "wp.bridges.long-document-handoff",
        }
        observed = []
        for card in manifest["cards"]:
            for program in ([True, False] if card["card_id"] in direct else [True]):
                contract = cycle._card_input_contract(schema, registry, card, program=program)
                observed.append((len(cycle._canonical(contract)), card["card_id"], program))
                self.assertFalse(set(contract["required_fields"]) & set(contract["optional_fields"]))
                self.assertEqual(set(contract["required_fields"]) | set(contract["optional_fields"]), set(contract["field_types"]))
                self.assertLessEqual(len(cycle._canonical(contract)), cycle.INPUT_CONTRACT_MAX_BYTES)
        self.assertEqual(15, len(observed))
        sample = json.loads(json.dumps(manifest["cards"][0]))
        for artifact_ids in ([], ["one", "two"]):
            sample["produced_artifact_ids"] = artifact_ids
            with self.assertRaises(cycle.CycleError):
                cycle._card_input_contract(schema, registry, sample, program=True)
        sample = manifest["cards"][0]
        missing_family = json.loads(json.dumps(registry))
        missing_family["artifacts"].pop(sample["produced_artifact_ids"][0])
        with self.assertRaises(cycle.CycleError):
            cycle._card_input_contract(schema, missing_family, sample, program=True)
        missing_definition = json.loads(json.dumps(registry))
        family_name = missing_definition["artifacts"][sample["produced_artifact_ids"][0]]
        missing_definition["families"][family_name]["human_def"] = "#/$defs/missing"
        with self.assertRaises(cycle.CycleError):
            cycle._card_input_contract(schema, missing_definition, sample, program=False)
        with mock.patch.object(cycle, "INPUT_CONTRACT_MAX_BYTES", 1), self.assertRaises(cycle.CycleError):
            cycle._card_input_contract(schema, registry, sample, program=True)
        with self.assertRaisesRegex(cycle.CycleError, "unknown root role"):
            cycle._input_contract(schema, registry, sample, "wp.complete.program-card/2", "#/$defs/programCardFields", always=["--source-root", "--unknown-root"], conditional=[])

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            (source / "input.txt").write_text("stable\n", encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, str(CLI), "route", "--input", "-", "--source-root", str(source)],
                input=json.dumps(self._route_command(), separators=(",", ":")),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("--fields-json", rejected.stderr)
            route = self._receipt(self._run("route", self._route_command(), source))
            route["schema_version"] = "wp-card-receipt/1"
            route["receipt_id"] = cycle._receipt_id(route)
            projection = source / "projection"
            projection.mkdir(mode=0o700)
            rejected_previous = self._run("complete", self._brief_command(route), source, "--projection-root", str(projection))
            self.assertNotEqual(0, rejected_previous.returncode)
            self.assertEqual("E_COMMAND_SCHEMA", json.loads(rejected_previous.stderr)["code"])
            self.assertEqual([], list(projection.iterdir()))

    def test_direct_spike_and_long_document_routes_have_one_completion_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            artifact = root / "artifact"
            source.mkdir()
            artifact.mkdir(mode=0o700)
            (source / "input.txt").write_text("stable\n", encoding="utf-8")

            spike_command = self._route_command()
            spike_command["fields"].update({"disposable_spike": True, "explicit_plan_request": False})
            spike_route = self._receipt(self._run("route", spike_command, source))
            self.assertEqual("wp.complete.card/2", spike_route["next_step"]["input_contract"]["completion_contract_id"])
            spike_complete = {
                "contract_id": "wp.complete.card/2", "invocation_phase": "initial", "previous_receipt": spike_route,
                "fields": {"claim": "One uncertainty is bounded", "observations": ["The probe is reproducible"], "limitations": [], "verdict": "proceed"},
                "outcome": {"blocker": None},
            }
            spike = self._receipt(self._run("complete", spike_complete, source))
            self.assertIsNone(spike["content_locator"])
            self.assertEqual([], list(artifact.iterdir()))

            long_command = self._route_command()
            long_command["fields"].update({"long_corpus_only": True, "explicit_plan_request": False})
            long_route = self._receipt(self._run("route", long_command, source))
            self.assertEqual(["--source-root", "--artifact-root"], long_route["next_step"]["input_contract"]["required_root_args"]["always"])
            long_complete = {
                "contract_id": "wp.complete.card/2", "invocation_phase": "initial", "previous_receipt": long_route,
                "fields": {
                    "document_goal": "Produce the bounded final plan", "source_ledger": ["source/input.txt"],
                    "coverage_matrix": ["all requirements mapped"], "recovery_packet": "resume from the final locator",
                    "next_sections": ["implementation"],
                },
                "outcome": {"blocker": None},
            }
            completed = self._receipt(self._run("complete", long_complete, source, "--artifact-root", str(artifact)))
            self.assertEqual("long-document-handoff", completed["content_locator"]["artifact_id"])
            files = list(artifact.iterdir())
            self.assertEqual(1, len(files))
            identity = (files[0].stat().st_ino, files[0].stat().st_mtime_ns)
            replay = self._receipt(self._run("complete", long_complete, source, "--artifact-root", str(artifact)))
            self.assertEqual(completed["content_locator"], replay["content_locator"])
            self.assertEqual(identity, (files[0].stat().st_ino, files[0].stat().st_mtime_ns))

    @staticmethod
    def _brief_command(receipt: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": "wp.complete.brief/2",
            "invocation_phase": "initial",
            "previous_receipt": receipt,
            "fields": {
                "outcome": "Ship one deterministic card-cycle command",
                "scope": "Writing Plans Brief projection only",
                "invariants": "No workflow state and no sibling JSON",
                "approach": "Validate, render, and publish one immutable projection",
                "proof": "Focused route-complete-idempotency tests",
                "risks_open_facts": "None",
                "completion": "One content-addressed Markdown projection",
            },
            "outcome": {"blocker": None},
        }

    @staticmethod
    def _handoff_command(receipt: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": "wp.complete.handoff/2",
            "invocation_phase": "initial",
            "previous_receipt": receipt,
            "fields": {
                "goal": "Transfer an executable bounded change",
                "non_goals": ["Grant execution authority"],
                "invariants": ["Receiver re-establishes scope and effects"],
                "owner_seams": ["src/owner.py::Owner"],
                "ordered_slices": ["Change the owner", "Run the focused verifier"],
                "required_evidence": ["E-01"],
                "rollback": "Restore the previous owner implementation",
            },
            "outcome": {"blocker": None},
        }

    def test_brief_route_complete_is_immutable_idempotent_and_fileless(self) -> None:
        self.assertTrue(SCHEMA.is_file(), "target protocol schema is absent")
        self.assertTrue(REGISTRY.is_file(), "target artifact registry is absent")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertTrue({"command", "receipt", "error", "contentLocator"} <= set(schema["$defs"]))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        brief_card = next(card for card in manifest["cards"] if card["card_id"] == "wp.profiles.brief")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            projection = root / "projection"
            source.mkdir()
            projection.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")

            route = self._receipt(self._run("route", self._route_command(), source))
            self.assertEqual("wp.profiles.brief", route["next_step"]["card_id"])
            self.assertEqual(brief_card["sha256"], route["next_step"]["card_hash"])
            command = self._brief_command(route)
            first = self._receipt(
                self._run("complete", command, source, "--projection-root", str(projection))
            )
            locator = first["content_locator"]
            self.assertEqual("projection", locator["content_kind"])
            self.assertEqual("plan-brief", locator["artifact_id"])
            outputs = list(projection.iterdir())
            self.assertEqual(1, len(outputs))
            self.assertEqual(".md", outputs[0].suffix)
            rendered = outputs[0].read_text(encoding="utf-8")
            self.assertIn("# Change Card: Ship one deterministic card-cycle command", rendered)
            identity = (outputs[0].stat().st_ino, outputs[0].stat().st_mtime_ns)

            replay = self._receipt(
                self._run("complete", command, source, "--projection-root", str(projection))
            )
            self.assertEqual(first, replay)
            self.assertEqual(identity, (outputs[0].stat().st_ino, outputs[0].stat().st_mtime_ns))
            self.assertEqual(["input.txt"], [path.name for path in source.iterdir()])
            self.assertFalse(any(path.suffix == ".json" or path.name.endswith(".tmp") for path in projection.iterdir()))

    def test_machine_fields_and_wrong_root_matrix_fail_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            projection = root / "projection"
            source.mkdir()
            projection.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route = self._receipt(self._run("route", self._route_command(), source))

            command = self._brief_command(route)
            command["fields"]["content_hash"] = "sha256:" + "0" * 64
            rejected = self._run("complete", command, source, "--projection-root", str(projection))
            self.assertEqual(2, rejected.returncode)
            self.assertEqual("", rejected.stdout)
            self.assertEqual("E_COMMAND_SCHEMA", json.loads(rejected.stderr)["code"])
            self.assertEqual([], list(projection.iterdir()))

            rejected = self._run("complete", self._brief_command(route), source)
            self.assertEqual(2, rejected.returncode)
            self.assertEqual("", rejected.stdout)
            self.assertEqual("E_ROOT_ROLE", json.loads(rejected.stderr)["code"])
            self.assertEqual([], list(projection.iterdir()))

            self._receipt(
                self._run("complete", self._brief_command(route), source, "--projection-root", str(projection))
            )
            output_name = next(projection.iterdir()).name
            foreign = root / "foreign"
            foreign.mkdir()
            (foreign / output_name).symlink_to("missing")
            rejected = self._run(
                "complete", self._brief_command(route), source, "--projection-root", str(foreign)
            )
            self.assertEqual(5, rejected.returncode)
            self.assertEqual("", rejected.stdout)
            self.assertEqual("E_ORPHAN_CONFLICT", json.loads(rejected.stderr)["code"])
            self.assertEqual([output_name], [path.name for path in foreign.iterdir()])

    def test_standalone_handoff_is_typed_immutable_and_does_not_claim_authority(self) -> None:
        schema = json.loads(HANDOFF_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            artifacts = root / "artifacts"
            projections = root / "projections"
            source.mkdir()
            artifacts.mkdir()
            projections.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route_command = self._route_command()
            route_command["fields"].update({"durable_handoff": True, "same_session_execution": False})
            route = self._receipt(self._run("route", route_command, source))
            self.assertEqual("wp.profiles.handoff", route["next_step"]["card_id"])
            command = self._handoff_command(route)
            first = self._receipt(self._run("complete", command, source, "--artifact-root", str(artifacts)))
            self.assertEqual("artifact", first["content_locator"]["content_kind"])
            output = next(artifacts.iterdir())
            artifact = json.loads(output.read_bytes())
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(artifact)))
            self.assertEqual("3.0", artifact["schema_version"])
            self.assertIn("sqw.select.control.scope-authority-and-effects", artifact["target_entry"]["required_decision_ids"])
            self.assertNotIn("authority_granted", artifact)
            render_command = {
                "contract_id": "wp.render.handoff/2", "invocation_phase": "resume",
                "previous_receipt": None, "fields": {"content_locator": first["content_locator"]},
                "outcome": {"blocker": None},
            }
            render_receipt = self._receipt(self._run(
                "render", render_command, source,
                "--artifact-root", str(artifacts), "--projection-root", str(projections),
            ))
            self.assertEqual("projection", render_receipt["content_locator"]["content_kind"])
            rendered = next(projections.iterdir()).read_text(encoding="utf-8")
            self.assertIn("does not grant or claim actual authority", rendered)
            self.assertNotIn(str(artifacts), rendered)
            identity = (output.stat().st_ino, output.stat().st_mtime_ns)
            replay = self._receipt(self._run("complete", command, source, "--artifact-root", str(artifacts)))
            self.assertEqual(first, replay)
            self.assertEqual(identity, (output.stat().st_ino, output.stat().st_mtime_ns))

    def test_content_locator_limits_match_program_state_constant(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        locator_schema = schema["$defs"]["contentLocator"]
        self.assertEqual(cycle.PROGRAM_STATE_MAX_BYTES, locator_schema["allOf"][0]["then"]["properties"]["bytes"]["maximum"])
        validator = Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/contentLocator"})

        def locator(kind: str, size: int) -> dict[str, object]:
            return {
                "schema_version": "content-locator/1", "content_kind": kind,
                "artifact_id": "bounded-output", "content_hash": "sha256:" + "0" * 64, "bytes": size,
            }

        self.assertFalse(list(validator.iter_errors(locator("owner", cycle.PROGRAM_STATE_MAX_BYTES))))
        self.assertTrue(list(validator.iter_errors(locator("owner", cycle.PROGRAM_STATE_MAX_BYTES + 1))))
        for kind in ("projection", "artifact"):
            self.assertFalse(list(validator.iter_errors(locator(kind, 32_768))))
            self.assertTrue(list(validator.iter_errors(locator(kind, 32_769))))

    def test_large_program_owner_is_valid_and_replays_without_growth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "program"
            source.mkdir()
            work.mkdir(mode=0o700)
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route_command = self._route_command()
            route_command["fields"].update({
                "resume_required": True, "same_session_execution": False,
                "independent_write_slices": 2, "strategy_family_count": 2,
            })
            route = self._receipt(self._run("route", route_command, source))
            init_command = {
                "contract_id": "wp.complete.program/2", "invocation_phase": "initial", "previous_receipt": route,
                "fields": {
                    "goal": "Prove the Program owner locator budget", "non_goals": ["Mutate source files"],
                    "invariants": ["a" * 16_000, "b" * 16_000], "initial_nodes": [],
                    "initial_queue": [{"decision_id": "wp.select.economy.output-projection", "subject_ref": None}],
                },
                "outcome": {"blocker": None},
            }
            initialized = self._receipt(self._run("complete", init_command, source, "--work-root", str(work)))
            self.assertGreater(initialized["content_locator"]["bytes"], 32_768)
            self.assertLessEqual(initialized["content_locator"]["bytes"], 57_344)
            self.assertEqual({".plan-state.lock", "plan-state.json", "artifacts", "projections"}, {path.name for path in work.iterdir()})
            resume_command = {
                "contract_id": "wp.route.resume/2", "invocation_phase": "resume", "previous_receipt": None,
                "fields": {"owner_locator": initialized["owner_locator"]}, "outcome": {"blocker": None},
            }
            resumed = self._receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertEqual(initialized["state_hash"], resumed["state_hash"])
            identity = {
                path.relative_to(work).as_posix(): (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_size)
                for path in work.rglob("*")
            }
            for _ in range(20):
                replay = self._receipt(self._run("complete", init_command, source, "--work-root", str(work)))
                self.assertTrue(replay["already_completed"])
                self.assertEqual(initialized["state_hash"], replay["state_hash"])
            self.assertEqual(identity, {
                path.relative_to(work).as_posix(): (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_size)
                for path in work.rglob("*")
            })

    def test_program_preflight_failures_leave_work_root_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route_command = self._route_command()
            route_command["fields"].update({"resume_required": True, "same_session_execution": False})
            route = self._receipt(self._run("route", route_command, source))
            command = {
                "contract_id": "wp.complete.program/2", "invocation_phase": "initial", "previous_receipt": route,
                "fields": {
                    "goal": "Reject invalid output before publication", "non_goals": ["Mutate source files"],
                    "invariants": ["Preserve the owner boundary"], "initial_nodes": [],
                    "initial_queue": [{"decision_id": "wp.select.economy.output-projection", "subject_ref": None}],
                },
                "outcome": {"blocker": None},
            }
            missing = root / "missing"
            with self.assertRaises(cycle.ProgramOwnerConflict) as missing_conflict:
                cycle.initialize_program_owner(missing, source, {})
            self.assertIn("non-retryable for this task", str(missing_conflict.exception))
            self.assertNotIn(str(missing), str(missing_conflict.exception))
            self.assertFalse(missing.exists())

            nested = source / "program"
            nested.mkdir(mode=0o700)
            with self.assertRaises(cycle.ProgramOwnerConflict) as nested_conflict:
                cycle.initialize_program_owner(nested, source, {})
            self.assertIn("stop without probing, mutation, retry, alternate root, or fallback", str(nested_conflict.exception))
            self.assertNotIn(str(nested), str(nested_conflict.exception))
            self.assertEqual([], list(nested.iterdir()))

            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            source_identity = cycle._capture_program_source(source)
            oversized = json.loads(json.dumps(command))
            oversized["fields"]["invariants"] = [character * 16_000 for character in "abcd"]
            oversized_work = root / "oversized"
            oversized_work.mkdir(mode=0o700)
            candidate = cycle._build_program_candidate(oversized["fields"], manifest, source_identity, oversized_work)
            self.assertGreater(len(cycle._canonical(candidate)) + 1, cycle.PROGRAM_STATE_MAX_BYTES)
            with self.assertRaisesRegex(cycle.CycleError, "Program owner exceeds the byte limit"):
                cycle._complete_program_init(schema, oversized, manifest, route, source, source_identity, oversized_work)
            self.assertEqual([], list(oversized_work.iterdir()))

            receipt_work = root / "receipt"
            receipt_work.mkdir(mode=0o700)
            with mock.patch.object(cycle, "RECEIPT_MAX_BYTES", 1), self.assertRaisesRegex(cycle.CycleError, "receipt exceeds the byte limit"):
                cycle._complete_program_init(schema, command, manifest, route, source, source_identity, receipt_work)
            self.assertEqual([], list(receipt_work.iterdir()))

            mismatched_schema = json.loads(json.dumps(schema))
            mismatched_schema["$defs"]["contentLocator"]["allOf"][0]["then"]["properties"]["bytes"]["maximum"] = 1
            schema_work = root / "schema"
            schema_work.mkdir(mode=0o700)
            with self.assertRaisesRegex(cycle.CycleError, "content_locator/bytes"):
                cycle._complete_program_init(mismatched_schema, command, manifest, route, source, source_identity, schema_work)
            self.assertEqual([], list(schema_work.iterdir()))

    def test_program_init_resume_output_completion_and_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "program"
            source.mkdir()
            work.mkdir(mode=0o700)
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route_command = self._route_command()
            route_command["fields"].update({
                "resume_required": True,
                "same_session_execution": False,
                "independent_write_slices": 2,
                "strategy_family_count": 2,
            })
            route = self._receipt(self._run("route", route_command, source))
            self.assertEqual("wp.profiles.program", route["next_step"]["card_id"])
            init_command = {
                "contract_id": "wp.complete.program/2",
                "invocation_phase": "initial",
                "previous_receipt": route,
                "fields": {
                    "goal": "Produce one locked Program projection",
                    "non_goals": ["Mutate source files"],
                    "invariants": ["Every accepted card increments state exactly once"],
                    "initial_nodes": [],
                    "initial_queue": [{"decision_id": "wp.select.economy.output-projection", "subject_ref": None}],
                },
                "outcome": {"blocker": None},
            }
            initialized = self._receipt(self._run("complete", init_command, source, "--work-root", str(work)))
            self.assertEqual(1, initialized["state_version"])
            self.assertEqual("wp.economy.output-projection", initialized["next_step"]["card_id"])
            self.assertEqual({".plan-state.lock", "plan-state.json", "artifacts", "projections"}, {path.name for path in work.iterdir()})
            resume_command = {
                "contract_id": "wp.route.resume/2", "invocation_phase": "resume",
                "previous_receipt": None, "fields": {"owner_locator": initialized["owner_locator"]},
                "outcome": {"blocker": None},
            }
            (source / "input.txt").write_text("eligible pre-card drift\n", encoding="utf-8")
            resumed = self._receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertEqual(initialized["state_hash"], resumed["state_hash"])
            self.assertTrue(resumed["source_rebind_required"])
            self.assertFalse(resumed["source_fresh"])
            complete_command = {
                "contract_id": "wp.complete.program-card/2", "invocation_phase": "resume",
                "previous_receipt": resumed,
                "fields": {
                    "owner_locator": resumed["owner_locator"],
                    "expected_state_version": resumed["state_version"],
                    "expected_content_hash": resumed["state_hash"],
                    "operations": [
                        {
                            "operation": "upsert_by_identity", "target": "nodes",
                            "value": {
                                "id": "P-01", "kind": "implementation", "status": "ready",
                                "objective": "Apply the bounded owner change", "depends_on": [], "inputs": [], "outputs": [],
                                "read_set": ["**"], "write_set": [], "resource_set": [], "effect_set": [],
                                "side_effect_level": "none",
                                "verifier": {
                                    "kind": "static", "completion_criterion": "The owner contract is preserved",
                                    "false_green_risk": "A stale projection could hide drift", "required_evidence": [],
                                },
                                "retry": {"allowed": True, "max_attempts": 1, "idempotency": "idempotent"},
                                "refinement": {"parent": None, "replaces": []},
                            },
                        },
                        {"operation": "replace_field", "target": "current_frontier", "value": ["P-01"]},
                    ],
                    "enqueue_requests": [{"decision_id": "wp.select.slicing.context-capsules", "subject_ref": "P-01"}],
                    "rationale": "Materialize the bounded current frontier", "evidence_refs": [],
                    "context": None, "runtime_projection": None,
                },
                "outcome": {"blocker": None},
            }
            completed = self._receipt(self._run("complete", complete_command, source, "--work-root", str(work)))
            self.assertEqual(2, completed["state_version"])
            self.assertFalse(completed["already_completed"])
            self.assertTrue(completed["source_fresh"])
            self.assertEqual("projection", completed["content_locator"]["content_kind"])
            self.assertEqual("wp.slicing.context-capsules", completed["next_step"]["card_id"])
            projection = work / "projections" / "program.md"
            self.assertTrue(projection.is_file())
            identity = (projection.stat().st_ino, projection.stat().st_mtime_ns)
            replay = self._receipt(self._run("complete", complete_command, source, "--work-root", str(work)))
            self.assertTrue(replay["already_completed"])
            self.assertEqual(completed["state_hash"], replay["state_hash"])
            self.assertEqual(identity, (projection.stat().st_ino, projection.stat().st_mtime_ns))

            context_route = self._receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertEqual("P-01", context_route["next_step"]["subject_ref"])
            context_command = {
                "contract_id": "wp.complete.program-card/2", "invocation_phase": "resume",
                "previous_receipt": context_route,
                "fields": {
                    "owner_locator": context_route["owner_locator"],
                    "expected_state_version": context_route["state_version"],
                    "expected_content_hash": context_route["state_hash"],
                    "operations": [],
                    "enqueue_requests": [{"decision_id": "wp.select.profiles.handoff", "subject_ref": "P-01"}],
                    "rationale": "Bind one bounded runtime projection", "evidence_refs": [],
                    "context": {"node_id": "P-01", "consumer_profile": "implementation", "budget_bytes": 8192},
                    "runtime_projection": {
                        "hard_failure_refs": [],
                        "remaining_budget": {
                            "iterations": 1, "candidate_evaluations": 1, "review_rounds": 1,
                            "changed_lines": 0, "total_changed_lines": 0,
                        },
                    },
                },
                "outcome": {"blocker": None},
            }
            context_completion = self._receipt(
                self._run("complete", context_command, source, "--work-root", str(work))
            )
            self.assertEqual(3, context_completion["state_version"])
            self.assertEqual("context-capsule", context_completion["content_locator"]["artifact_id"])
            self.assertTrue((work / "projections" / "context-capsule.md").is_file())
            state = json.loads((work / "plan-state.json").read_bytes())
            self.assertEqual(context_command["fields"]["runtime_projection"], state["last_transition"]["inline_render_completion"]["runtime_projection"])
            self.assertNotIn("content_locator", state["last_transition"])
            state_bytes = (work / "plan-state.json").read_bytes()
            capsule = work / "projections" / "context-capsule.md"
            capsule_bytes = capsule.read_bytes()
            capsule.unlink()
            render_command = {
                "contract_id": "wp.render.program/2", "invocation_phase": "resume",
                "previous_receipt": None,
                "fields": {"owner_locator": context_completion["owner_locator"], "projection_kind": "context-capsule"},
                "outcome": {"blocker": None},
            }
            rendered = self._receipt(self._run("render", render_command, source, "--work-root", str(work)))
            self.assertEqual("context-capsule", rendered["content_locator"]["artifact_id"])
            self.assertEqual(capsule_bytes, capsule.read_bytes())
            self.assertEqual(state_bytes, (work / "plan-state.json").read_bytes())

            handoff_route = self._receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertEqual("wp.profiles.handoff", handoff_route["next_step"]["card_id"])
            handoff_command = {
                "contract_id": "wp.complete.program-card/2", "invocation_phase": "resume",
                "previous_receipt": handoff_route,
                "fields": {
                    "owner_locator": handoff_route["owner_locator"],
                    "expected_state_version": handoff_route["state_version"],
                    "expected_content_hash": handoff_route["state_hash"],
                    "operations": [], "enqueue_requests": [],
                    "rationale": "Materialize the typed receiver boundary", "evidence_refs": [],
                    "context": None, "runtime_projection": None,
                },
                "outcome": {"blocker": None},
            }
            handoff_completion = self._receipt(
                self._run("complete", handoff_command, source, "--work-root", str(work))
            )
            self.assertEqual(4, handoff_completion["state_version"])
            self.assertEqual("artifact", handoff_completion["content_locator"]["content_kind"])
            artifact_file = next((work / "artifacts").glob("*.json"))
            artifact = json.loads(artifact_file.read_bytes())
            handoff_schema = json.loads(HANDOFF_SCHEMA.read_text(encoding="utf-8"))
            self.assertEqual([], list(Draft202012Validator(handoff_schema).iter_errors(artifact)))
            artifact_identity = (artifact_file.stat().st_ino, artifact_file.stat().st_mtime_ns)
            handoff_replay = self._receipt(
                self._run("complete", handoff_command, source, "--work-root", str(work))
            )
            self.assertTrue(handoff_replay["already_completed"])
            self.assertEqual(handoff_completion["content_locator"], handoff_replay["content_locator"])
            self.assertEqual(artifact_identity, (artifact_file.stat().st_ino, artifact_file.stat().st_mtime_ns))
            committed_state = (work / "plan-state.json").read_bytes()
            stale_capsule = capsule.read_bytes()
            stale_render = self._run("render", render_command, source, "--work-root", str(work))
            self.assertEqual(3, stale_render.returncode)
            self.assertEqual("E_CONTEXT_NOT_CURRENT", json.loads(stale_render.stderr)["code"])
            self.assertEqual(stale_capsule, capsule.read_bytes())
            self.assertEqual(committed_state, (work / "plan-state.json").read_bytes())
            (source / "input.txt").write_text("eligible dirty leaf\n", encoding="utf-8")
            stale_terminal = self._receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertFalse(stale_terminal["source_fresh"])
            self.assertFalse(stale_terminal["source_rebind_required"])
            self.assertEqual("program_ready", stale_terminal["next_step"]["status"])
            self.assertEqual(committed_state, (work / "plan-state.json").read_bytes())
            artifact_file.unlink()
            rejected = self._run("route", resume_command, source, "--work-root", str(work))
            self.assertEqual(5, rejected.returncode)
            self.assertEqual("E_ORPHAN_CONFLICT", json.loads(rejected.stderr)["code"])
            self.assertEqual(committed_state, (work / "plan-state.json").read_bytes())

    def test_registry_covers_every_artifact_with_one_fixed_family_class(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        expected = {
            artifact_id: family
            for family, artifact_ids in self.FAMILY_ARTIFACTS.items()
            for artifact_id in artifact_ids
        }
        produced = {
            artifact_id
            for card in manifest["cards"]
            for artifact_id in card["produced_artifact_ids"]
        }
        self.assertEqual(10, len(produced))
        self.assertEqual(expected, registry["artifacts"])
        self.assertEqual(produced, set(expected))
        self.assertEqual(set(self.FAMILY_ARTIFACTS), set(registry["families"]))
        self.assertEqual(
            {
                "plan-delta": "semantic_inline", "evidence": "semantic_inline",
                "brief": "immutable_projection", "handoff": "boundary_by_contract",
                "program": "semantic_inline", "output-projection": "owner_disposable_projection",
                "context-capsule": "owner_disposable_projection",
                "long-document-handoff": "boundary_by_contract",
            },
            {name: contract["persistence_class"] for name, contract in registry["families"].items()},
        )
        for contract in registry["families"].values():
            self.assertEqual("required", contract["source_binding"])
            for field in ("human_def", "payload_def"):
                self.assertIn(contract[field].split("/")[-1], schema["$defs"])

    def test_repository_source_route_uses_head_bound_identity_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "repo"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            (source / "input.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "input.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "fixture"], check=True)
            before = subprocess.run(["git", "-C", str(source), "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
            receipt = self._receipt(self._run("route", self._route_command(), source))
            self.assertEqual("repository", receipt["source_identity"]["kind"])
            after = subprocess.run(["git", "-C", str(source), "status", "--porcelain"], text=True, capture_output=True, check=True).stdout
            self.assertEqual(before, after)

    def test_source_contained_brief_uses_four_observations_and_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "repo"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            (source / "input.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "input.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "fixture"], check=True)
            projections = source / "plans"
            projections.mkdir()
            route = self._receipt(self._run("route", self._route_command(), source))
            command = self._brief_command(route)
            first = self._receipt(self._run(
                "complete", command, source, "--projection-root", str(projections)
            ))
            self.assertEqual("plan-output", first["source_transition"]["operation_kind"])
            self.assertEqual("added", first["source_transition"]["changed_paths"][0]["status"])
            target = next(projections.iterdir())
            identity = (target.stat().st_ino, target.stat().st_mtime_ns)
            replay = self._receipt(self._run(
                "complete", command, source, "--projection-root", str(projections)
            ))
            self.assertEqual(first, replay)
            self.assertEqual(identity, (target.stat().st_ino, target.stat().st_mtime_ns))
            (source / "outside.txt").write_text("drift\n", encoding="utf-8")
            blocked = self._run("complete", command, source, "--projection-root", str(projections))
            self.assertEqual(3, blocked.returncode)
            self.assertEqual("E_SOURCE_REVISION_CHANGED", json.loads(blocked.stderr)["code"])

    def test_source_contained_repository_publication_uses_exact_fourteen_git_children(self) -> None:
        real_popen = subprocess.Popen
        calls: list[list[str]] = []

        def spy(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
            calls.append(argv)
            return real_popen(argv, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            source = BoundedGitObserverTests._repository(Path(directory))
            with mock.patch.object(cycle.subprocess, "Popen", side_effect=spy):
                kind, session, before = cycle._open_publication_capture(source)
                (source / "plan.md").write_text("projection\n", encoding="utf-8")
                after = cycle._publication_fence(kind, session)
            after_identity, transition = cycle._publication_transition(before, after, "plan.md")
        self.assertEqual("repository", after_identity["kind"])
        self.assertEqual("plan.md", transition["changed_paths"][0]["path"])
        self.assertEqual(14, len(calls))

    def test_source_contained_handoff_and_projection_replay_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "repo"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
            (source / "input.txt").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "input.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "fixture"], check=True)
            artifacts = source / "artifacts"
            projections = source / "projections"
            artifacts.mkdir()
            projections.mkdir()
            route_command = self._route_command()
            route_command["fields"].update({"durable_handoff": True, "same_session_execution": False})
            route = self._receipt(self._run("route", route_command, source))
            command = self._handoff_command(route)
            first = self._receipt(self._run("complete", command, source, "--artifact-root", str(artifacts)))
            replay = self._receipt(self._run("complete", command, source, "--artifact-root", str(artifacts)))
            self.assertEqual(first, replay)
            render_command = {
                "contract_id": "wp.render.handoff/2", "invocation_phase": "resume",
                "previous_receipt": None, "fields": {"content_locator": first["content_locator"]},
                "outcome": {"blocker": None},
            }
            rendered = self._receipt(self._run(
                "render", render_command, source,
                "--artifact-root", str(artifacts), "--projection-root", str(projections),
            ))
            render_replay = self._receipt(self._run(
                "render", render_command, source,
                "--artifact-root", str(artifacts), "--projection-root", str(projections),
            ))
            self.assertEqual(rendered, render_replay)
            self.assertEqual("plan-output", rendered["source_transition"]["operation_kind"])


if __name__ == "__main__":
    unittest.main()
