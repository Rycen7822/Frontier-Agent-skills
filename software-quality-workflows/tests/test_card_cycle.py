from __future__ import annotations

import json
from hashlib import sha256
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
STATE_SCHEMA = ROOT / "schemas" / "workflow-state.schema.json"


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
            "contract_id": "sqw.route.initial/1",
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

    def _entry_command(self, receipt: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": "sqw.complete.entry/1",
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

    def _scope_command(self, receipt: dict[str, object], *, mode: str = "M0") -> dict[str, object]:
        return {
            "contract_id": "sqw.complete.scope/1",
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
