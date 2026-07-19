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


if __name__ == "__main__":
    unittest.main()
