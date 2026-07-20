from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "card_cycle.py"
SCHEMA = ROOT / "schemas" / "card-protocol.schema.json"
REGISTRY = ROOT / "registries" / "artifact-family-contracts.json"
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"
HANDOFF_SCHEMA = ROOT / "schemas" / "plan-execution-handoff.schema.json"


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

    def _receipt(self, completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("", completed.stderr)
        self.assertEqual(1, len(completed.stdout.splitlines()))
        self.assertLessEqual(len(completed.stdout.encode("utf-8")), 12_288)
        return json.loads(completed.stdout)

    @staticmethod
    def _route_command() -> dict[str, object]:
        return {
            "contract_id": "wp.route.initial/1",
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

    @staticmethod
    def _brief_command(receipt: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": "wp.complete.brief/1",
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
            "contract_id": "wp.complete.handoff/1",
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
                "contract_id": "wp.render.handoff/1", "invocation_phase": "resume",
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
                "contract_id": "wp.complete.program/1",
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
                "contract_id": "wp.route.resume/1", "invocation_phase": "resume",
                "previous_receipt": None, "fields": {"owner_locator": initialized["owner_locator"]},
                "outcome": {"blocker": None},
            }
            (source / "input.txt").write_text("eligible pre-card drift\n", encoding="utf-8")
            resumed = self._receipt(self._run("route", resume_command, source, "--work-root", str(work)))
            self.assertEqual(initialized["state_hash"], resumed["state_hash"])
            self.assertTrue(resumed["source_rebind_required"])
            self.assertFalse(resumed["source_fresh"])
            complete_command = {
                "contract_id": "wp.complete.program-card/1", "invocation_phase": "resume",
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
                "contract_id": "wp.complete.program-card/1", "invocation_phase": "resume",
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
                "contract_id": "wp.render.program/1", "invocation_phase": "resume",
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
                "contract_id": "wp.complete.program-card/1", "invocation_phase": "resume",
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


if __name__ == "__main__":
    unittest.main()
