from __future__ import annotations

import json
from hashlib import sha256
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
STATE_SCHEMA = ROOT / "schemas" / "workflow-state.schema.json"
SCRIPT_DIRECTORY = ROOT / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
SPEC = importlib.util.spec_from_file_location("sqw_card_cycle_under_test", CLI)
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
        subprocess.run(["git", "-C", str(source), "config", "user.email", "sqw@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "SQW"], check=True)
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
                identity, observation = cycle._capture_source(source)
        self.assertEqual("repository", identity["kind"])
        self.assertEqual("repository", observation["kind"])
        self.assertEqual(8, len(calls))
        self.assertEqual(2, sum(argv[8:10] == ["rev-parse", "HEAD^{commit}"] for argv in calls))
        self.assertEqual(2, sum(argv[8:10] == ["ls-files", "-v"] for argv in calls))
        self.assertEqual(2, sum(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))

    def test_unversioned_capture_uses_two_python_observations_and_no_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "input.txt").write_text("stable\n", encoding="utf-8")
            with mock.patch.object(cycle, "_unversioned_observation", wraps=cycle._unversioned_observation) as observer:
                with mock.patch.object(cycle.subprocess, "Popen", side_effect=AssertionError("unexpected Git child")):
                    cycle._capture_source(source)
            self.assertEqual(2, observer.call_count)

    def test_exact_safe_status_config_values_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self._repository(Path(directory))
            for key, value in (
                ("core.fileMode", "true"), ("core.ignoreStat", "false"),
                ("core.trustCtime", "true"), ("core.checkStat", "default"),
            ):
                subprocess.run(["git", "-C", str(source), "config", key, value], check=True)
            identity, _ = cycle._capture_source(source)
            self.assertEqual("repository", identity["kind"])

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
                            cycle._capture_source(source)
                    self.assertFalse(any(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))

            flagged_root = parent / "flagged"
            flagged_root.mkdir()
            flagged = self._repository(flagged_root)
            subprocess.run(["git", "-C", str(flagged), "update-index", "--assume-unchanged", "input.txt"], check=True)
            calls = []
            with mock.patch.object(cycle.subprocess, "Popen", side_effect=lambda argv, **kwargs: (calls.append(argv), real_popen(argv, **kwargs))[1]):
                with self.assertRaises(cycle.CycleError):
                    cycle._capture_source(flagged)
            self.assertFalse(any(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))
            nested_root = parent / "nested"
            nested_root.mkdir()
            repository = self._repository(nested_root)
            nested = repository / "child"
            nested.mkdir()
            calls = []
            with mock.patch.object(cycle.subprocess, "Popen", side_effect=lambda argv, **kwargs: (calls.append(argv), real_popen(argv, **kwargs))[1]):
                with self.assertRaises(cycle.CycleError):
                    cycle._capture_source(nested)
            self.assertFalse(any(argv[8:10] == ["status", "--porcelain=v2"] for argv in calls))
        with self.assertRaises(cycle.CycleError):
            cycle._parse_index(b"H 100644 " + b"0" * 40 + b" 1\tconflict.txt\0")

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


class CardCycleM0Tests(unittest.TestCase):
    FAMILY_ARTIFACTS = {
        "intake": {"workflow-intake"},
        "scope": {"control-scope-authority-and-effects"},
        "gate": {
            "control-evidence-and-verifier-integrity",
            "verify-classification-and-completion",
            "verify-gate-selection-and-execution",
        },
        "handoff": {
            "bridges-multi-source-synthesis",
            "bridges-source-target-gap-audit",
            "delegation-admission-and-contract",
            "delegation-fan-in-and-integration",
        },
        "review-result": {
            "review-execution", "review-result", "review-tier",
            "review-rubrics-accessibility", "review-rubrics-adversarial-decision",
            "review-rubrics-engineering-integrity", "review-rubrics-ml-ai",
            "review-rubrics-privacy-data-lifecycle", "review-rubrics-product-and-operability",
            "review-rubrics-secret-handling",
        },
        "decision": {
            "intent-discovery-and-freeze", "domain-api-contract-and-migration",
            "domain-architecture-boundaries-and-alternatives", "domain-architecture-migration-proof",
            "domain-browser-content-security", "recovery-cleanup", "recovery-conflict-recovery",
            "recovery-repository-recovery", "workspace-artifact-and-fixture-ownership",
            "workspace-prototype-lifecycle",
        },
        "evidence": {
            "diagnosis-evidence-and-hypothesis", "domain-browser-evidence-and-readiness",
            "domain-observability-signal-and-recovery", "domain-performance-baseline-and-parity",
            "domain-plugin-package-registration-and-installed-proof", "domain-runtime-version-and-consistency",
            "domain-security-trust-boundary-and-negatives", "domain-source-external-authority",
            "recipes-dependency-lockfile-drift", "runtime-stability-campaign", "test-behavior-cycle",
            "test-oracle-and-lifecycle", "test-patterns-contract-migration-proof",
            "test-patterns-dashboard-evidence", "test-patterns-evaluation-fixture-curation",
            "test-patterns-implementation-parity", "test-patterns-optional-postprocess-boundary",
            "test-patterns-protocol-tool-stress", "test-patterns-public-adapter-migration-proof",
        },
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
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                subcommand,
                "--input",
                "-",
                "--source-root",
                str(source_root),
                *extra,
            ],
            input=json.dumps(command, ensure_ascii=False, separators=(",", ":")),
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def _success_receipt(self, completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("", completed.stderr)
        self.assertEqual(1, len(completed.stdout.splitlines()))
        payload = json.loads(completed.stdout)
        self.assertLessEqual(len(completed.stdout.encode("utf-8")), 12_288)
        self.assertNotIn("previous_receipt", payload)
        return payload

    def _initial_command(self, **overrides: object) -> dict[str, object]:
        command = {
            "contract_id": "sqw.route.initial/2",
            "invocation_phase": "initial",
            "previous_receipt": None,
            "fields": {
                "request_mode": "change",
                "intent_status": "adequate",
                "root_cause_status": "known",
                "implicated_surfaces": ["public_contract", "test_fixture_benchmark"],
                "unknown_implicated_facts": [],
                "persistence_need": "none",
                "delegation_need": "none",
                "external_side_effect": "none",
            },
            "outcome": {"blocker": None},
        }
        command["fields"].update(overrides)
        return command

    def test_route_help_and_all_card_input_contracts_are_compact_and_exact(self) -> None:
        outputs = []
        for columns in ("20", "200"):
            env = {**os.environ, "LC_ALL": "C", "COLUMNS": columns, "PYTHONDONTWRITEBYTECODE": "1"}
            completed = subprocess.run([sys.executable, str(CLI), "route", "--help"], text=True, capture_output=True, check=False, env=env)
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual("", completed.stderr)
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertLessEqual(len(outputs[0].encode("utf-8")), 1_280)
        lines = outputs[0].splitlines()
        self.assertEqual("usage: card_cycle.py route --input - --source-root PATH [--work-root PATH]", lines[0])
        initial = json.loads(lines[1].removeprefix("initial_input_contract="))
        self.assertEqual("sqw.route.initial/2", initial["contract_id"])
        reconstructed = dict(initial["fixed_command"])
        reconstructed[initial["route_fields_key"]] = self._initial_command()["fields"]
        self.assertEqual(self._initial_command(), reconstructed)
        self.assertEqual({
            "implicated_surfaces": {"enum": cycle.SURFACE_FAMILIES},
            "unknown_implicated_facts": {"subset_of": "implicated_surfaces"},
        }, initial["field_constraints"])
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "subject.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            self._success_receipt(self._run("route", reconstructed, source))
        groups = initial["required_fields"]
        projected = [name for group in (groups["boolean"], groups["string_array"], groups["integer_min"], groups["enum"]) for name in group]
        schema, registry, manifest = cycle._load_contracts()
        self.assertEqual(sorted(schema["$defs"]["routeFields"]["required"]), sorted(projected))
        self.assertEqual(len(projected), len(set(projected)))

        observed = []
        for card in manifest["cards"]:
            contract = cycle._card_input_contract(schema, registry, card)
            observed.append((len(cycle._canonical(contract)), card["card_id"]))
            self.assertEqual({
                "completion_contract_id", "artifact_id", "persistence_class", "required_fields",
                "optional_fields", "enum_values", "field_types", "human_max_bytes", "required_root_args",
            }, set(contract))
            self.assertFalse(set(contract["required_fields"]) & set(contract["optional_fields"]))
            self.assertEqual(set(contract["required_fields"]) | set(contract["optional_fields"]), set(contract["field_types"]))
            self.assertLessEqual(len(cycle._canonical(contract)), cycle.INPUT_CONTRACT_MAX_BYTES)
        self.assertEqual(52, len(observed))
        entry_contract = cycle._card_input_contract(schema, registry, next(card for card in manifest["cards"] if card["card_id"].startswith("sqw.entry.")))
        self.assertEqual("string[]", entry_contract["field_types"]["protected_paths"])
        self.assertEqual("string[]", entry_contract["field_types"]["proof_requirements"])
        scope = cycle._card_input_contract(schema, registry, next(card for card in manifest["cards"] if card["card_id"] == "sqw.control.scope-authority-and-effects"))
        self.assertEqual([{"arg": "--work-root", "field": "mode", "in": ["M2", "M3"]}], scope["required_root_args"]["conditional"])
        sample = json.loads(json.dumps(manifest["cards"][0]))
        for artifact_ids in ([], ["one", "two"]):
            sample["produced_artifact_ids"] = artifact_ids
            with self.assertRaises(cycle.CycleError):
                cycle._card_input_contract(schema, registry, sample)
        sample = manifest["cards"][0]
        missing_family = json.loads(json.dumps(registry))
        missing_family["artifacts"].pop(sample["produced_artifact_ids"][0])
        with self.assertRaises(cycle.CycleError):
            cycle._card_input_contract(schema, missing_family, sample)
        missing_definition = json.loads(json.dumps(registry))
        family_name = missing_definition["artifacts"][sample["produced_artifact_ids"][0]]
        missing_definition["families"][family_name]["human_def"] = "#/$defs/missing"
        with self.assertRaises(cycle.CycleError):
            cycle._card_input_contract(schema, missing_definition, sample)
        with mock.patch.object(cycle, "INPUT_CONTRACT_MAX_BYTES", 1), self.assertRaises(cycle.CycleError):
            cycle._card_input_contract(schema, registry, sample)
        with self.assertRaisesRegex(cycle.CycleError, "unknown root role"):
            cycle._input_contract(schema, registry, sample, "sqw.complete.entry/2", "#/$defs/entryFields", always=["--source-root", "--unknown-root"], conditional=[])

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            (source / "input.txt").write_text("stable\n", encoding="utf-8")
            stale = self._initial_command()
            stale["contract_id"] = "sqw.route.initial/1"
            rejected = self._run("route", stale, source)
            self.assertNotEqual(0, rejected.returncode)
            self.assertEqual("E_COMMAND_SCHEMA", json.loads(rejected.stderr)["code"])
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            route["schema_version"] = "sqw-card-receipt/1"
            route["receipt_id"] = cycle._receipt_id(route)
            rejected_previous = self._run("complete", self._entry_command(route), source)
            self.assertNotEqual(0, rejected_previous.returncode)
            self.assertEqual("E_COMMAND_SCHEMA", json.loads(rejected_previous.stderr)["code"])
            self.assertEqual(["input.txt"], sorted(path.name for path in source.iterdir()))

    def _entry_command(self, receipt: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": "sqw.complete.entry/2",
            "invocation_phase": "initial",
            "previous_receipt": receipt,
            "fields": {
                "intent": "replace model-written control JSON with one deterministic card cycle",
                "root_cause": "machine identity and routing fields are serialized by the model",
                "current_behavior": "no card-cycle command exists",
                "expected_behavior": "the command returns a bounded replacement receipt",
                "protected_paths": ["input.txt"],
                "proof_requirements": ["m0-chain", "zero-runtime-files"],
            },
            "outcome": {"blocker": None},
        }

    def _resume_command(self, receipt: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": "sqw.route.resume/2",
            "invocation_phase": "resume",
            "previous_receipt": None,
            "fields": {"owner_locator": receipt["owner_locator"]},
        }

    def _active_evidence_command(self, receipt: dict[str, object], decision_request: str | None) -> dict[str, object]:
        return {
            "contract_id": "sqw.complete.card/2",
            "invocation_phase": "active",
            "previous_receipt": receipt,
            "fields": {
                "claim": "The routed behavior is proven.",
                "observations": ["The focused contract test passed."],
                "limitations": [],
                "verdict": "pass",
            },
            "outcome": {"blocker": None, "decision_request": decision_request},
        }

    def _active_handoff_command(self, receipt: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": "sqw.complete.card/2",
            "invocation_phase": "active",
            "previous_receipt": receipt,
            "fields": {
                "objective": "Hand off the bounded implementation slice.",
                "requirements": ["Preserve the verified contract."],
                "authority_requirements": ["Local reversible writes only."],
                "ordered_slices": ["Implement", "Verify"],
                "rollback": "Revert the bounded patch.",
            },
            "outcome": {"blocker": None, "decision_request": None},
        }

    def _render_command(self, receipt: dict[str, object], budget_bytes: int = 8192) -> dict[str, object]:
        return {
            "contract_id": "sqw.render.context/2",
            "invocation_phase": "render",
            "previous_receipt": receipt,
            "fields": {"budget_bytes": budget_bytes},
        }

    def _scope_command(self, receipt: dict[str, object], *, mode: str = "M0") -> dict[str, object]:
        return {
            "contract_id": "sqw.complete.scope/2",
            "invocation_phase": "initial",
            "previous_receipt": receipt,
            "fields": {
                "mode": mode,
                "allowed_reads": ["input.txt"],
                "allowed_writes": ["target.txt"],
                "effects": ["LOCAL_REVERSIBLE"],
                "approval_requirements": [],
                "publication_ceiling": "none",
            },
            "outcome": {"blocker": None},
        }

    def test_direct_change_scope_m0_chain_is_flat_and_fileless(self) -> None:
        self.assertTrue(SCHEMA.is_file(), "target protocol schema is absent")
        self.assertTrue(REGISTRY.is_file(), "target artifact registry is absent")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertTrue({"command", "receipt", "error"} <= set(schema["$defs"]))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cards = {card["card_id"]: card for card in manifest["cards"]}

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            source.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")

            route = self._success_receipt(self._run("route", self._initial_command(), source))
            self.assertEqual("route", route["receipt_kind"])
            self.assertEqual("unversioned", route["source_identity"]["kind"])
            self.assertEqual("sqw.entry.direct-change", route["next_step"]["card_id"])
            self.assertEqual(cards["sqw.entry.direct-change"]["sha256"], route["next_step"]["card_hash"])

            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            self.assertEqual("completion", entry["receipt_kind"])
            self.assertEqual("sqw.control.scope-authority-and-effects", entry["next_step"]["card_id"])
            self.assertNotEqual(route["receipt_id"], entry["receipt_id"])

            scope = self._success_receipt(self._run("complete", self._scope_command(entry), source))
            self.assertEqual("M0", scope["scope_binding"]["mode"])
            self.assertEqual("sqw.test.behavior-cycle", scope["next_step"]["card_id"])
            self.assertNotEqual(entry["receipt_id"], scope["receipt_id"])
            self.assertEqual(["input.txt"], [path.name for path in source.iterdir()])

    def test_machine_fields_and_m0_work_root_fail_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route = self._success_receipt(self._run("route", self._initial_command(), source))

            entry_command = self._entry_command(route)
            entry_command["fields"]["card_hash"] = "sha256:" + "0" * 64
            rejected = self._run("complete", entry_command, source)
            self.assertEqual(2, rejected.returncode)
            self.assertEqual("", rejected.stdout)
            self.assertEqual(1, len(rejected.stderr.splitlines()))
            self.assertEqual("E_COMMAND_SCHEMA", json.loads(rejected.stderr)["code"])
            self.assertEqual(["input.txt"], [path.name for path in source.iterdir()])
            self.assertEqual([], list(work.iterdir()))

            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            rejected = self._run(
                "complete",
                self._scope_command(entry),
                source,
                "--work-root",
                str(work),
            )
            self.assertEqual(2, rejected.returncode)
            self.assertEqual("", rejected.stdout)
            self.assertEqual("E_ROOT_ROLE", json.loads(rejected.stderr)["code"])
            self.assertEqual(["input.txt"], [path.name for path in source.iterdir()])
            self.assertEqual([], list(work.iterdir()))

    def test_every_initial_entry_crosses_scope_once_before_its_first_work_card(self) -> None:
        cases = [
            ({}, "sqw.entry.direct-change", "sqw.test.behavior-cycle"),
            ({"root_cause_status": "unknown"}, "sqw.entry.diagnose-failure", "sqw.diagnosis.evidence-and-hypothesis"),
            ({"intent_status": "materially_underdefined"}, "sqw.entry.intent-discovery", "sqw.intent.discovery-and-freeze"),
            ({"request_mode": "report"}, "sqw.entry.read-only-audit", "sqw.verify.classification-and-completion"),
            ({"request_mode": "review"}, "sqw.entry.read-only-audit", "sqw.review.tier-selection"),
            ({"request_mode": "recovery"}, "sqw.entry.recovery", "sqw.recovery.repository-recovery"),
        ]
        for overrides, entry_card, work_card in cases:
            with self.subTest(entry=entry_card, work=work_card), tempfile.TemporaryDirectory() as temp_dir:
                source = Path(temp_dir) / "source"
                source.mkdir()
                (source / "input.txt").write_text("stable input\n", encoding="utf-8")
                route = self._success_receipt(self._run("route", self._initial_command(**overrides), source))
                self.assertEqual(entry_card, route["next_step"]["card_id"])
                entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
                self.assertEqual("sqw.control.scope-authority-and-effects", entry["next_step"]["card_id"])
                scope = self._success_receipt(self._run("complete", self._scope_command(entry), source))
                self.assertEqual(work_card, scope["next_step"]["card_id"])

    def test_m2_scope_bootstrap_is_exact_replayable_and_has_one_owner_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            command = self._scope_command(entry, mode="M2")
            first = self._success_receipt(
                self._run("complete", command, source, "--work-root", str(work))
            )
            self.assertEqual("sqw-workflow-owner/1", first["owner_locator"]["schema_version"])
            self.assertEqual(
                [".adapter.lock", "artifacts", "locks.json", "projections", "state.json"],
                sorted(path.name for path in work.iterdir()),
            )
            state_path = work / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state_schema = json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))
            self.assertEqual([], list(Draft202012Validator(state_schema).iter_errors(state)))
            self.assertEqual(("3.0", "M2", 1), (state["schema_version"], state["mode"], state["state_version"]))
            declared_hash = state.pop("state_hash")
            canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.assertEqual("sha256:" + sha256(canonical).hexdigest(), declared_hash)
            state["state_hash"] = declared_hash
            for filename in (".adapter.lock", "state.json", "locks.json"):
                self.assertEqual(0o600, (work / filename).stat().st_mode & 0o777)
            for dirname in ("artifacts", "projections"):
                self.assertEqual(0o700, (work / dirname).stat().st_mode & 0o777)
            identity = (state_path.stat().st_ino, state_path.stat().st_mtime_ns, state_path.read_bytes())
            replay = self._success_receipt(
                self._run("complete", command, source, "--work-root", str(work))
            )
            self.assertEqual(first, replay)
            self.assertEqual(identity, (state_path.stat().st_ino, state_path.stat().st_mtime_ns, state_path.read_bytes()))
            self.assertFalse((work / "events.jsonl").exists())
            self.assertFalse(any(path.name.endswith(".tmp") for path in work.iterdir()))

            locks_path = work / "locks.json"
            owner_identity = {
                path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                for path in (state_path, locks_path)
            }
            resumed = self._success_receipt(
                self._run("route", self._resume_command(first), source, "--work-root", str(work))
            )
            self.assertEqual(first["owner_locator"], resumed["owner_locator"])
            self.assertEqual((state["state_version"], state["state_hash"]), (resumed["state_version"], resumed["state_hash"]))
            self.assertEqual(first["next_step"], resumed["next_step"])
            self.assertEqual(first["current_lease"], resumed["current_lease"])
            self.assertEqual(
                owner_identity,
                {
                    path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                    for path in (state_path, locks_path)
                },
            )

            bad_resume = self._resume_command(first)
            bad_resume["fields"]["owner_locator"] = dict(first["owner_locator"])
            bad_resume["fields"]["owner_locator"]["bootstrap_operation_id"] = "sha256:" + "0" * 64
            rejected_resume = self._run("route", bad_resume, source, "--work-root", str(work))
            self.assertEqual(5, rejected_resume.returncode)
            self.assertEqual("E_ORPHAN_CONFLICT", json.loads(rejected_resume.stderr)["code"])
            self.assertEqual(
                owner_identity,
                {
                    path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                    for path in (state_path, locks_path)
                },
            )

            (source / "input.txt").write_text("changed input\n", encoding="utf-8")
            drifted = self._success_receipt(
                self._run("route", self._resume_command(first), source, "--work-root", str(work))
            )
            self.assertEqual(("blocked", "source-out-of-scope", None), (drifted["next_step"]["kind"], drifted["next_step"]["reason_code"], drifted["current_lease"]))
            self.assertEqual(owner_identity["state.json"], (state_path.stat().st_ino, state_path.stat().st_mtime_ns, state_path.read_bytes()))
            self.assertEqual([], json.loads(locks_path.read_text(encoding="utf-8"))["leases"])
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            first = self._success_receipt(
                self._run("route", self._resume_command(first), source, "--work-root", str(work))
            )

            expired = json.loads(locks_path.read_text(encoding="utf-8"))
            expired["leases"][0]["lease_expires_at"] = "2000-01-01T00:00:00Z"
            locks_path.write_text(
                json.dumps(expired, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            replacement = self._success_receipt(
                self._run("route", self._resume_command(first), source, "--work-root", str(work))
            )
            self.assertNotEqual(first["current_lease"]["lease_id"], replacement["current_lease"]["lease_id"])
            self.assertEqual(identity, (state_path.stat().st_ino, state_path.stat().st_mtime_ns, state_path.read_bytes()))
            self.assertFalse((work / ".locks.json.tmp").exists())

            foreign = root / "foreign"
            foreign.mkdir()
            sentinel = foreign / "sentinel.txt"
            sentinel.write_text("owned elsewhere\n", encoding="utf-8")
            before = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
            rejected = self._run("complete", command, source, "--work-root", str(foreign))
            self.assertEqual(5, rejected.returncode)
            self.assertEqual("", rejected.stdout)
            self.assertEqual("E_ORPHAN_CONFLICT", json.loads(rejected.stderr)["code"])
            self.assertEqual(before, (sentinel.read_bytes(), sentinel.stat().st_mtime_ns))
            self.assertEqual(["sentinel.txt"], [path.name for path in foreign.iterdir()])

    def test_context_render_uses_fixed_owner_projection_and_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            scoped = self._success_receipt(
                self._run("complete", self._scope_command(entry, mode="M2"), source, "--work-root", str(work))
            )
            state_path = work / "state.json"
            locks_path = work / "locks.json"
            owner_identity = {
                path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                for path in (state_path, locks_path)
            }
            command = self._render_command(scoped)
            rendered = self._success_receipt(self._run("render", command, source, "--work-root", str(work)))
            projection_path = work / "projections" / "workflow-context.md"
            self.assertTrue(projection_path.is_file())
            self.assertEqual(0o600, projection_path.stat().st_mode & 0o777)
            self.assertEqual(rendered["projection_locator"]["bytes"], len(projection_path.read_bytes()))
            self.assertIn(b"sqw-workflow-context/1", projection_path.read_bytes().splitlines()[0])
            self.assertEqual(
                owner_identity,
                {
                    path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                    for path in (state_path, locks_path)
                },
            )
            projection_identity = (projection_path.stat().st_ino, projection_path.stat().st_mtime_ns, projection_path.read_bytes())
            replay = self._success_receipt(self._run("render", command, source, "--work-root", str(work)))
            self.assertFalse(rendered["already_completed"])
            self.assertTrue(replay["already_completed"])
            self.assertEqual(rendered["projection_locator"], replay["projection_locator"])
            self.assertEqual(projection_identity, (projection_path.stat().st_ino, projection_path.stat().st_mtime_ns, projection_path.read_bytes()))
            self.assertFalse((work / "projections" / "workflow-context.md.tmp").exists())

    def test_source_nested_work_root_and_v2_owner_are_zero_write_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            source_file = source / "input.txt"
            source_file.write_text("stable input\n", encoding="utf-8")
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            command = self._scope_command(entry, mode="M2")

            nested = source / "workflow"
            nested.mkdir()
            source_before = (source_file.read_bytes(), source_file.stat().st_mtime_ns)
            rejected_nested = self._run("complete", command, source, "--work-root", str(nested))
            self.assertEqual(5, rejected_nested.returncode)
            self.assertEqual("E_ORPHAN_CONFLICT", json.loads(rejected_nested.stderr)["code"])
            self.assertEqual([], list(nested.iterdir()))
            self.assertEqual(source_before, (source_file.read_bytes(), source_file.stat().st_mtime_ns))

            work = root / "work"
            work.mkdir()
            scoped = self._success_receipt(self._run("complete", command, source, "--work-root", str(work)))
            state_path = work / "state.json"
            retired = json.loads(state_path.read_text(encoding="utf-8"))
            retired["schema_version"] = "2.0"
            retired.pop("state_hash")
            retired["state_hash"] = "sha256:" + sha256(
                json.dumps(retired, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            state_path.write_text(
                json.dumps(retired, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            control_before = {
                name: ((work / name).stat().st_ino, (work / name).stat().st_mtime_ns, (work / name).read_bytes())
                for name in (".adapter.lock", "state.json", "locks.json")
            }
            rejected_v2 = self._run("route", self._resume_command(scoped), source, "--work-root", str(work))
            self.assertEqual(5, rejected_v2.returncode)
            self.assertEqual("E_ORPHAN_CONFLICT", json.loads(rejected_v2.stderr)["code"])
            self.assertEqual(
                control_before,
                {
                    name: ((work / name).stat().st_ino, (work / name).stat().st_mtime_ns, (work / name).read_bytes())
                    for name in (".adapter.lock", "state.json", "locks.json")
                },
            )
            self.assertEqual([], list((work / "artifacts").iterdir()))
            self.assertEqual([], list((work / "projections").iterdir()))

    def test_durable_inline_completion_advances_once_and_terminal_clears_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            scoped = self._success_receipt(
                self._run("complete", self._scope_command(entry, mode="M2"), source, "--work-root", str(work))
            )

            behavior_command = self._active_evidence_command(scoped, "sqw.select.test.oracle-and-lifecycle")
            behavior = self._success_receipt(
                self._run("complete", behavior_command, source, "--work-root", str(work))
            )
            self.assertEqual((2, "sqw.test.oracle-and-lifecycle"), (behavior["state_version"], behavior["next_step"]["card_id"]))
            state_path = work / "state.json"
            locks_path = work / "locks.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(behavior["state_hash"], state["state_hash"])
            self.assertEqual(behavior["completion"]["content_hash"], state["last_transition"]["completion_id"])
            self.assertEqual(behavior["current_lease"], json.loads(locks_path.read_text(encoding="utf-8"))["leases"][0])
            committed_identity = {
                path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                for path in (state_path, locks_path)
            }
            replay = self._success_receipt(
                self._run("complete", behavior_command, source, "--work-root", str(work))
            )
            self.assertFalse(behavior["already_completed"])
            self.assertTrue(replay["already_completed"])
            for key in ("completion", "next_step", "current_lease", "state_version", "state_hash"):
                self.assertEqual(behavior[key], replay[key])
            self.assertEqual(
                committed_identity,
                {
                    path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                    for path in (state_path, locks_path)
                },
            )

            terminal_command = self._active_evidence_command(behavior, None)
            terminal = self._success_receipt(
                self._run("complete", terminal_command, source, "--work-root", str(work))
            )
            self.assertEqual((3, "terminal", None), (terminal["state_version"], terminal["next_step"]["kind"], terminal["current_lease"]))
            terminal_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(("completed", None), (terminal_state["status"], terminal_state["active_frontier"]))
            self.assertEqual([], json.loads(locks_path.read_text(encoding="utf-8"))["leases"])
            terminal_resume = self._success_receipt(
                self._run("route", self._resume_command(terminal), source, "--work-root", str(work))
            )
            self.assertEqual(("terminal", None, 3), (terminal_resume["next_step"]["kind"], terminal_resume["current_lease"], terminal_resume["state_version"]))

    def test_durable_handoff_is_materialized_once_without_payload_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            scoped = self._success_receipt(
                self._run("complete", self._scope_command(entry, mode="M2"), source, "--work-root", str(work))
            )
            behavior = self._success_receipt(
                self._run(
                    "complete",
                    self._active_evidence_command(scoped, "sqw.select.delegation.admission-and-contract"),
                    source,
                    "--work-root",
                    str(work),
                )
            )
            command = self._active_handoff_command(behavior)
            completed = self._success_receipt(self._run("complete", command, source, "--work-root", str(work)))
            locator = completed["completion"]["content_locator"]
            artifact_path = work / "artifacts" / f"{locator['artifact_id']}--{locator['content_hash'][7:]}.json"
            self.assertTrue(artifact_path.is_file())
            self.assertEqual(locator["bytes"], len(artifact_path.read_bytes()))
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            self.assertEqual(locator["content_hash"], "sha256:" + sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest())
            state = json.loads((work / "state.json").read_text(encoding="utf-8"))
            stored = state["card_completions"][-1]
            self.assertEqual("materialized", stored["storage"])
            self.assertEqual(locator, stored["content_locator"])
            self.assertNotIn("completion", stored)
            self.assertNotIn("fields", completed["completion"])
            identity = {
                path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                for path in (work / "state.json", work / "locks.json", artifact_path)
            }
            replay = self._success_receipt(self._run("complete", command, source, "--work-root", str(work)))
            self.assertFalse(completed["already_completed"])
            self.assertTrue(replay["already_completed"])
            for key in ("completion", "next_step", "current_lease", "state_version", "state_hash"):
                self.assertEqual(completed[key], replay[key])
            self.assertEqual(
                identity,
                {
                    path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                    for path in (work / "state.json", work / "locks.json", artifact_path)
                },
            )
            self.assertEqual([artifact_path.name], sorted(path.name for path in (work / "artifacts").iterdir()))
            control_identity = {
                path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                for path in (work / "state.json", work / "locks.json")
            }
            artifact_path.write_text("{}\n", encoding="utf-8")
            rejected = self._run("route", self._resume_command(completed), source, "--work-root", str(work))
            self.assertEqual(5, rejected.returncode)
            self.assertEqual("E_ORPHAN_CONFLICT", json.loads(rejected.stderr)["code"])
            self.assertEqual(
                control_identity,
                {
                    path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                    for path in (work / "state.json", work / "locks.json")
                },
            )

    def test_in_scope_source_drift_is_bound_once_and_accepted_by_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            scoped = self._success_receipt(
                self._run("complete", self._scope_command(entry, mode="M2"), source, "--work-root", str(work))
            )
            (source / "target.txt").write_text("authorized change\n", encoding="utf-8")
            resume_command = self._resume_command(scoped)
            drifted = self._success_receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertFalse(drifted["source_fresh"])
            transition = drifted["pending_source_transition"]
            self.assertEqual([{"path": "target.txt", "status": "added"}], transition["changed_paths"])
            self.assertEqual(scoped["source_identity"]["identity_hash"], transition["before_identity_hash"])
            self.assertEqual(drifted["source_identity"]["identity_hash"], transition["after_identity_hash"])
            self.assertNotEqual(scoped["current_lease"]["lease_id"], drifted["current_lease"]["lease_id"])
            replay = self._success_receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertEqual(drifted, replay)

            completed = self._success_receipt(
                self._run(
                    "complete",
                    self._active_evidence_command(drifted, "sqw.select.test.oracle-and-lifecycle"),
                    source,
                    "--work-root",
                    str(work),
                )
            )
            state = json.loads((work / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(drifted["source_identity"], state["source_identity"])
            self.assertEqual(transition, state["card_completions"][-1]["completion"]["source_transition"])
            self.assertTrue(completed["source_fresh"])
            self.assertIsNone(completed["pending_source_transition"])
            state_path = work / "state.json"
            state_identity = (state_path.stat().st_ino, state_path.stat().st_mtime_ns, state_path.read_bytes())
            (source / "input.txt").write_text("out of scope change\n", encoding="utf-8")
            blocked = self._success_receipt(
                self._run("route", self._resume_command(completed), source, "--work-root", str(work))
            )
            self.assertEqual(("blocked", "source-out-of-scope"), (blocked["next_step"]["kind"], blocked["next_step"]["reason_code"]))
            self.assertEqual((False, None, None), (blocked["source_fresh"], blocked["pending_source_transition"], blocked["current_lease"]))
            self.assertEqual([], json.loads((work / "locks.json").read_text(encoding="utf-8"))["leases"])
            self.assertEqual(state_identity, (state_path.stat().st_ino, state_path.stat().st_mtime_ns, state_path.read_bytes()))
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            recovered = self._success_receipt(
                self._run("route", self._resume_command(completed), source, "--work-root", str(work))
            )
            self.assertEqual(("card", True), (recovered["next_step"]["kind"], recovered["source_fresh"]))
            self.assertIsNotNone(recovered["current_lease"])

    def test_repository_dirty_write_is_pending_but_head_change_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "SQW Test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "sqw@example.invalid"], check=True)
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            (source / "target.txt").write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "input.txt", "target.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "baseline"], check=True)
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            self.assertEqual("repository", route["source_identity"]["kind"])
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            scoped = self._success_receipt(
                self._run("complete", self._scope_command(entry, mode="M2"), source, "--work-root", str(work))
            )
            outside = source / "outside.txt"
            outside.write_text("untracked exterior\n", encoding="utf-8")
            outside_blocked = self._success_receipt(
                self._run("route", self._resume_command(scoped), source, "--work-root", str(work))
            )
            self.assertEqual(("blocked", "source-out-of-scope"), (outside_blocked["next_step"]["kind"], outside_blocked["next_step"]["reason_code"]))
            outside.unlink()
            recovered = self._success_receipt(
                self._run("route", self._resume_command(scoped), source, "--work-root", str(work))
            )
            self.assertTrue(recovered["source_fresh"])
            (source / "target.txt").rename(outside)
            rename_blocked = self._success_receipt(
                self._run("route", self._resume_command(scoped), source, "--work-root", str(work))
            )
            self.assertEqual(("blocked", "source-out-of-scope"), (rename_blocked["next_step"]["kind"], rename_blocked["next_step"]["reason_code"]))
            outside.rename(source / "target.txt")
            (source / "target.txt").write_text("dirty allowed write\n", encoding="utf-8")
            dirty = self._success_receipt(
                self._run("route", self._resume_command(scoped), source, "--work-root", str(work))
            )
            self.assertEqual([{"path": "target.txt", "status": "modified"}], dirty["pending_source_transition"]["changed_paths"])
            subprocess.run(["git", "-C", str(source), "add", "target.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "advance head"], check=True)
            blocked = self._success_receipt(
                self._run("route", self._resume_command(scoped), source, "--work-root", str(work))
            )
            self.assertEqual(("blocked", "source-revision-changed", None), (blocked["next_step"]["kind"], blocked["next_step"]["reason_code"], blocked["current_lease"]))
            self.assertEqual([], json.loads((work / "locks.json").read_text(encoding="utf-8"))["leases"])

    def test_ignored_exact_allowed_write_is_captured_without_scanning_other_ignored_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            work = root / "work"
            source.mkdir()
            work.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "SQW Test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "sqw@example.invalid"], check=True)
            (source / ".gitignore").write_text("target.txt\ncache/\n", encoding="utf-8")
            (source / "input.txt").write_text("stable input\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", ".gitignore", "input.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-q", "-m", "baseline"], check=True)
            route = self._success_receipt(self._run("route", self._initial_command(), source))
            entry = self._success_receipt(self._run("complete", self._entry_command(route), source))
            scoped = self._success_receipt(
                self._run("complete", self._scope_command(entry, mode="M2"), source, "--work-root", str(work))
            )
            cache = source / "cache"
            cache.mkdir()
            (cache / "noise.bin").write_bytes(b"ignored noise")
            (source / "target.txt").write_text("authorized ignored output\n", encoding="utf-8")
            resumed = self._success_receipt(
                self._run("route", self._resume_command(scoped), source, "--work-root", str(work))
            )
            self.assertEqual([{"path": "target.txt", "status": "added"}], resumed["pending_source_transition"]["changed_paths"])

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
        self.assertEqual(48, len(produced))
        self.assertEqual(expected, registry["artifacts"])
        self.assertEqual(produced, set(expected))
        self.assertEqual(set(self.FAMILY_ARTIFACTS), set(registry["families"]))
        self.assertEqual(
            {
                "intake": "semantic_inline", "scope": "semantic_inline",
                "decision": "semantic_inline", "evidence": "semantic_inline",
                "gate": "semantic_inline", "handoff": "boundary_by_contract",
                "review-result": "semantic_inline",
            },
            {name: contract["persistence_class"] for name, contract in registry["families"].items()},
        )
        for contract in registry["families"].values():
            self.assertEqual("required", contract["source_binding"])
            for field in ("human_def", "payload_def"):
                self.assertIn(contract[field].split("/")[-1], schema["$defs"])


if __name__ == "__main__":
    unittest.main()
