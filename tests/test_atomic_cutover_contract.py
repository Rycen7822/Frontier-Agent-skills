from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_TARGETS = {
    "writing-plans": ("7.0.0", 10),
    "software-quality-workflows": ("8.0.0", 52),
}
CORE_CLOSURE = re.compile(
    r"autonomous_" + r"closure|wp\." + r"closure\.|sqw\." + r"closure\."
    + r"|closure[-_ ](?:admission|contract|phase|artifact|state|event)",
    re.IGNORECASE,
)
CORE_GRAPH = re.compile(
    r"neigh" + r"bor|max_active_" + r"neigh" + r"bors|reference-card-" + r"graph|edge-" + r"golden",
    re.IGNORECASE,
)

ENTRY_REQUIRED_TEXT = (
    "LC_ALL=C scripts/card_cycle.py route --help",
    "scripts/card_cycle.py route --input -",
    "target repository root, never this skill root",
    "card_path",
    "card_hash",
    "input_contract",
    "required_root_args.always",
    "conditional",
    "replacement receipt",
    "entire current replacement receipt",
    "receipt chain",
    "scripts/card_cycle.py complete --input -",
    "scripts/card_cycle.py render --input -",
    "semantic_inline",
    "raw state",
    "whole artifact/projection directories",
)
ANCHOR_TEMPLATE = (
    "owner=<skill>/<owner-kind> | root=<exact task root> | locator=<immutable owner locator> | "
    "source=<source identity> | bundle=<bundle identity> | "
    "lifecycle=<active|terminal-retain|terminal-disposable> | "
    "boundary=<none or named consumer/evidence ref>"
)


class _ConstrainedCaller:
    """Deterministic model-side caller with an explicit, testable read surface."""

    VALUES: dict[str, object] = {
        "intent": "complete one bounded card cycle",
        "root_cause": "the runtime contract is known",
        "current_behavior": "the bounded entry is active",
        "expected_behavior": "the replacement receipt advances once",
        "protected_paths": ["input.txt"],
        "proof_requirements": ["focused contract test"],
        "mode": "M0",
        "allowed_reads": ["input.txt"],
        "allowed_writes": ["target.txt"],
        "effects": ["LOCAL_REVERSIBLE"],
        "approval_requirements": [],
        "publication_ceiling": "none",
        "outcome": "Publish one bounded plan brief",
        "scope": "The plan projection only",
        "invariants": "No owner state or protocol siblings",
        "approach": "Validate and publish one immutable projection",
        "proof": "Focused route-complete replay",
        "risks_open_facts": "None",
        "completion": "One content-addressed Markdown projection",
    }

    def __init__(self, skill: str, source: Path) -> None:
        self.skill = skill
        execution_root = os.environ.get("FRONTIER_V8V7_EXECUTION_SKILLS_ROOT")
        self.skill_root = (Path(execution_root) if execution_root else ROOT) / skill
        self.cli = self.skill_root / "scripts" / "card_cycle.py"
        self.source = source
        self.model_reads: list[Path] = []

    def read_entry(self) -> str:
        path = self.skill_root / "SKILL.md"
        self.model_reads.append(path)
        return path.read_text(encoding="utf-8")

    def help_contract(self) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(self.cli), "route", "--help"],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode != 0 or completed.stderr:
            raise AssertionError(completed.stderr)
        return json.loads(completed.stdout.splitlines()[1].removeprefix("initial_input_contract="))

    def invoke(self, action: str, command: dict[str, object], *root_args: str) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, str(self.cli), action, "--input", "-", "--source-root", str(self.source), *root_args],
            input=json.dumps(command, separators=(",", ":")),
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode != 0 or completed.stderr:
            raise AssertionError(completed.stderr)
        if len(completed.stdout.splitlines()) != 1:
            raise AssertionError("receipt stdout must be one line")
        receipt = json.loads(completed.stdout)
        if "previous_receipt" in receipt:
            raise AssertionError("receipt chain leaked")
        return receipt

    def read_returned_card(self, receipt: dict[str, object]) -> None:
        step = receipt["next_step"]
        card = (self.skill_root / step["card_path"]).resolve(strict=True)
        if self.skill_root.resolve() not in card.parents:
            raise AssertionError("card escaped skill root")
        self.model_reads.append(card)
        payload = card.read_bytes()
        if "sha256:" + hashlib.sha256(payload).hexdigest() != step["card_hash"]:
            raise AssertionError("returned card hash mismatch")

    def completion(self, receipt: dict[str, object]) -> dict[str, object]:
        contract = receipt["next_step"]["input_contract"]
        required = contract["required_fields"]
        missing = [field for field in required if field not in self.VALUES]
        if missing:
            raise AssertionError(f"no deterministic value for {missing}")
        return {
            "contract_id": contract["completion_contract_id"],
            "invocation_phase": "initial",
            "previous_receipt": receipt,
            "fields": {field: self.VALUES[field] for field in required},
            "outcome": {"blocker": None},
        }

    def assert_read_surface(self) -> None:
        forbidden = {"schemas", "registries", "fixtures", "state.json", "plan-state.json", "events.jsonl", "package-support-map.md"}
        for path in self.model_reads:
            relative = path.relative_to(self.skill_root)
            if any(part in forbidden for part in relative.parts):
                raise AssertionError(f"forbidden model read: {relative}")
        if len(self.model_reads) != len(set(self.model_reads)):
            raise AssertionError("model reread an entry or card")


class AtomicCutoverContractTests(unittest.TestCase):
    @staticmethod
    def _load(path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_bundle_identity_is_the_exact_atomic_target(self) -> None:
        manifest = self._load(ROOT / "bundle-manifest.json")
        generated = self._load(ROOT / "frontier-engineering.bundle.json")
        self.assertEqual("2.0", manifest["bundle_schema_version"])
        self.assertEqual("4.0.0", manifest["bundle_version"])
        self.assertEqual(
            [("writing-plans", "7.0.0"), ("software-quality-workflows", "8.0.0")],
            [(skill["id"], skill["version"]) for skill in manifest["skills"]],
        )
        self.assertEqual(
            ["plan-to-workflow", "workflow-plan-change-proposal"],
            manifest["cross_skill_contracts"],
        )
        self.assertEqual(
            {
                "current_level": "implicit_local_pilot",
                "implicit_routing_default": True,
                "remote_writes": False,
            },
            manifest["activation_policy"],
        )
        self.assertEqual("frontier-engineering-bundle/1.0", generated["schema_version"])
        self.assertEqual("frontier-engineering/8.0.0+7.0.0", generated["bundle_id"])
        self.assertEqual(2, generated["compatible_schema_epoch"])

    def test_active_card_inventory_and_static_economy_are_exact(self) -> None:
        total_card_bytes = 0
        for skill, (version, count) in SKILL_TARGETS.items():
            with self.subTest(skill=skill):
                manifest = self._load(ROOT / skill / "registries" / "reference-cards.manifest.json")
                self.assertEqual(version, manifest["skill_version"])
                self.assertEqual(count, len(manifest["cards"]))
                self.assertTrue(all(card["bytes"] <= 8192 for card in manifest["cards"]))
                total_card_bytes += sum(card["bytes"] for card in manifest["cards"])
        self.assertLessEqual(total_card_bytes, 190000)
        self.assertLessEqual(
            (ROOT / "writing-plans" / "SKILL.md").stat().st_size
            + (ROOT / "software-quality-workflows" / "SKILL.md").stat().st_size,
            12500,
        )

    def test_model_entries_are_closed_over_the_card_cycle(self) -> None:
        limits = {"writing-plans": 5200, "software-quality-workflows": 7200}
        raw_selector_command = re.compile(
            r"`[^`]*(?:assess_plan_mode|route_workflow)\.py\s+(?:--|route|complete|render)[^`]*`"
        )
        for skill, maximum in limits.items():
            with self.subTest(skill=skill):
                path = ROOT / skill / "SKILL.md"
                text = path.read_text(encoding="utf-8")
                self.assertLessEqual(path.stat().st_size, maximum)
                for required in ENTRY_REQUIRED_TEXT:
                    self.assertIn(required, text)
                self.assertIn(ANCHOR_TEMPLATE, text)
                self.assertIsNone(raw_selector_command.search(text))
                for action in ("route", "complete", "render"):
                    command_spans = re.findall(rf"`([^`]*\.py {action}(?:\s|`)[^`]*)`", text)
                    self.assertTrue(command_spans, action)
                    self.assertTrue(all("scripts/card_cycle.py" in span for span in command_spans))
                self.assertIn("Replacement stops", text)
                self.assertIn("physical context eviction", text)

    def test_core_closure_protocol_has_no_residual(self) -> None:
        residuals: list[str] = []
        for skill in SKILL_TARGETS:
            for path in sorted((ROOT / skill).rglob("*")):
                if not path.is_file() or path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if (
                    CORE_CLOSURE.search(text)
                    or CORE_GRAPH.search(text)
                    or "closure" in path.relative_to(ROOT / skill).parts
                ):
                    residuals.append(path.relative_to(ROOT).as_posix())
        for path in (ROOT / "bundle-manifest.json", ROOT / "frontier-engineering.bundle.json"):
            text = path.read_text(encoding="utf-8")
            if CORE_CLOSURE.search(text) or CORE_GRAPH.search(text):
                residuals.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], residuals)


class RuntimeSafetyContractTests(unittest.TestCase):
    def test_default_runtime_has_no_interception_or_remote_execution_surface(self) -> None:
        runtime_paths = (
            "software-quality-workflows/scripts/card_cycle.py",
            "software-quality-workflows/scripts/route_workflow.py",
            "software-quality-workflows/scripts/_workflow_reference_cards.py",
            "software-quality-workflows/scripts/_workflow_state.py",
            "software-quality-workflows/scripts/local_workflow_adapter.py",
            "writing-plans/scripts/card_cycle.py",
            "writing-plans/scripts/assess_plan_mode.py",
            "writing-plans/scripts/_writing_reference_cards.py",
            "writing-plans/scripts/_plan_state.py",
        )
        forbidden_import_roots = {
            "aiohttp", "anthropic", "boto3", "httpx", "keyring", "openai", "paramiko",
            "requests", "socket", "ssl", "urllib.request",
        }
        for relative in runtime_paths:
            path = ROOT / relative
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            self.assertTrue(forbidden_import_roots.isdisjoint(imports), relative)
            if relative.endswith("/card_cycle.py"):
                self.assertFalse("os.environ" in source, relative)
                self.assertTrue("subprocess.Popen(" in source, relative)
                self.assertFalse("subprocess.run(" in source, relative)
                self.assertTrue("selectors.DefaultSelector()" in source, relative)

        for skill in SKILL_TARGETS:
            metadata = yaml.safe_load((ROOT / skill / "agents" / "openai.yaml").read_text(encoding="utf-8"))
            self.assertEqual({"interface", "policy"}, set(metadata), skill)
            self.assertEqual({"allow_implicit_invocation"}, set(metadata["policy"]), skill)
            self.assertTrue(metadata["policy"]["allow_implicit_invocation"], skill)


class BoundedCallerAndAnchorContractTests(unittest.TestCase):
    SQW_ROUTE_FIELDS = {
        "request_mode": "change",
        "intent_status": "adequate",
        "root_cause_status": "known",
        "implicated_surfaces": ["public_contract"],
        "unknown_implicated_facts": [],
        "persistence_need": "none",
        "delegation_need": "none",
        "external_side_effect": "none",
    }
    WP_ROUTE_FIELDS = {
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
    }

    @staticmethod
    def _route_command(contract_id: str, fields: dict[str, object]) -> dict[str, object]:
        return {
            "contract_id": contract_id,
            "invocation_phase": "initial",
            "previous_receipt": None,
            "fields": fields,
            "outcome": {"blocker": None},
        }

    def test_constrained_caller_completes_sqw_m0_and_wp_brief(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sqw_source = root / "sqw-source"
            wp_source = root / "wp-source"
            projection = root / "wp-projection"
            for path in (sqw_source, wp_source, projection):
                path.mkdir()
            (sqw_source / "input.txt").write_text("stable\n", encoding="utf-8")
            (wp_source / "input.txt").write_text("stable\n", encoding="utf-8")

            sqw = _ConstrainedCaller("software-quality-workflows", sqw_source)
            self.assertIn("Card-cycle entry", sqw.read_entry())
            self.assertEqual("sqw.route.initial/2", sqw.help_contract()["contract_id"])
            receipt = sqw.invoke("route", self._route_command("sqw.route.initial/2", self.SQW_ROUTE_FIELDS))
            sqw.read_returned_card(receipt)
            receipt = sqw.invoke("complete", sqw.completion(receipt))
            sqw.read_returned_card(receipt)
            receipt = sqw.invoke("complete", sqw.completion(receipt))
            self.assertEqual("M0", receipt["scope_binding"]["mode"])
            self.assertEqual(["input.txt"], [path.name for path in sqw_source.iterdir()])
            sqw.assert_read_surface()

            wp = _ConstrainedCaller("writing-plans", wp_source)
            self.assertIn("Card-cycle entry", wp.read_entry())
            self.assertEqual("wp.route.initial/2", wp.help_contract()["contract_id"])
            route = wp.invoke("route", self._route_command("wp.route.initial/2", self.WP_ROUTE_FIELDS))
            wp.read_returned_card(route)
            command = wp.completion(route)
            first = wp.invoke("complete", command, "--projection-root", str(projection))
            outputs = list(projection.iterdir())
            self.assertEqual(1, len(outputs))
            self.assertEqual(".md", outputs[0].suffix)
            identity = (outputs[0].stat().st_ino, outputs[0].stat().st_mtime_ns, outputs[0].stat().st_size)
            replay = wp.invoke("complete", command, "--projection-root", str(projection))
            self.assertEqual(first, replay)
            self.assertEqual(identity, (outputs[0].stat().st_ino, outputs[0].stat().st_mtime_ns, outputs[0].stat().st_size))
            self.assertEqual(["input.txt"], [path.name for path in wp_source.iterdir()])
            self.assertFalse(any(path.suffix == ".json" or "receipt" in path.name or "worknote" in path.name for path in projection.iterdir()))
            wp.assert_read_surface()

    def test_twenty_tasks_have_isolated_single_anchor_lifecycles(self) -> None:
        modes = ("M0", "M1", "Brief", "Handoff", "M2", "M3", "Program")
        anchors: dict[str, str] = {}
        retained: list[tuple[str, Path]] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            source = base / "source"
            owners = base / "owners"
            deliveries = base / "deliveries"
            source.mkdir()
            owners.mkdir()
            deliveries.mkdir()
            for index in range(20):
                task = f"task-{index:02d}"
                mode = modes[index % len(modes)]
                task_source = source / task
                task_source.mkdir()
                if mode in {"M0", "M1"}:
                    self.assertNotIn(task, anchors)
                    continue
                if mode in {"Brief", "Handoff"}:
                    delivery = deliveries / f"{task}.md"
                    delivery.write_text(f"{mode} delivery\n", encoding="utf-8")
                    self.assertNotIn(task, anchors)
                    continue

                owner_root = owners / task
                owner_root.mkdir()
                owner_file = owner_root / "owner.state"
                owner_file.write_text("immutable owner\n", encoding="utf-8")
                owner_kind = "program" if mode == "Program" else "workflow"
                anchors[task] = (
                    f"owner={'writing-plans' if mode == 'Program' else 'software-quality-workflows'}/{owner_kind} | "
                    f"root={owner_root} | locator={owner_file} | source=source:{task} | bundle=bundle:test | "
                    "lifecycle=active | boundary=none"
                )
                self.assertNotIn(str(task_source), anchors[task])
                self.assertEqual(1, sum(key == task for key in anchors))
                self.assertFalse(any("receipt" in path.name for path in owner_root.iterdir()))

                if index % 2 == 0:
                    anchors[task] = anchors[task].replace("lifecycle=active", "lifecycle=terminal-disposable")
                    owner_file.unlink()
                    owner_root.rmdir()
                    self.assertFalse(owner_root.exists())
                    del anchors[task]
                else:
                    anchors[task] = anchors[task].replace(
                        "lifecycle=active | boundary=none",
                        f"lifecycle=terminal-retain | boundary=consumer:{task}",
                    )
                    retained.append((task, owner_root))

            for task, owner_root in retained:
                self.assertTrue(owner_root.exists())
                self.assertIn(f"boundary=consumer:{task}", anchors[task])
                anchors[task] = anchors[task].replace("lifecycle=terminal-retain", "lifecycle=terminal-disposable")
                (owner_root / "owner.state").unlink()
                owner_root.rmdir()
                self.assertFalse(owner_root.exists())
                del anchors[task]
            self.assertEqual({}, anchors)


class PromptInputContractTest(unittest.TestCase):
    @staticmethod
    def _regular_bytes(path: Path, maximum: int) -> bytes:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or info.st_size > maximum
        ):
            raise AssertionError(f"unsafe discovery input: {path}")
        payload = path.read_bytes()
        if len(payload) != info.st_size:
            raise AssertionError(f"discovery input changed while reading: {path}")
        return payload

    def test_isolated_prompt_input(self) -> None:
        prompt_value = os.environ.get("FRONTIER_V8V7_PROMPT_INPUT")
        skills_value = os.environ.get("FRONTIER_V8V7_DISCOVERY_SKILLS_ROOT")
        if prompt_value is None and skills_value is None:
            self.skipTest("isolated prompt-input evidence was not requested")
        self.assertIsNotNone(prompt_value)
        self.assertIsNotNone(skills_value)
        prompt_path = Path(prompt_value)
        skills_root = Path(skills_value)
        prompt_payload = self._regular_bytes(prompt_path, 8_388_608)
        prompt = json.loads(prompt_payload.decode("utf-8", errors="strict"))
        self.assertIsInstance(prompt, list)
        prompt_texts: list[str] = []
        for item in prompt:
            self.assertIsInstance(item, dict)
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if isinstance(content_item, dict) and content_item.get("type") == "input_text":
                    text = content_item.get("text")
                    self.assertIsInstance(text, str)
                    prompt_texts.append(text.replace("\r\n", "\n"))
        self.assertTrue(prompt_texts)

        root_info = skills_root.lstat()
        self.assertTrue(stat.S_ISDIR(root_info.st_mode))
        self.assertEqual(os.geteuid(), root_info.st_uid)
        skill_entries = {path.name for path in skills_root.iterdir()}
        self.assertEqual(set(SKILL_TARGETS), skill_entries - {".system"})
        locator_text = "\n".join(prompt_texts)
        for skill, (version, card_count) in SKILL_TARGETS.items():
            skill_root = skills_root / skill
            for path in skill_root.rglob("*"):
                info = path.lstat()
                self.assertFalse(stat.S_ISLNK(info.st_mode), path)
                self.assertEqual(os.geteuid(), info.st_uid, path)
                self.assertTrue(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), path)
            skill_path = skill_root / "SKILL.md"
            frontmatter = self._regular_bytes(skill_path, 16_384).decode("utf-8", errors="strict").split("---", 2)[1]
            metadata = yaml.safe_load(frontmatter)
            self.assertEqual(skill, metadata["name"])
            self.assertEqual(version, metadata["metadata"]["version"])
            agent_metadata = yaml.safe_load(
                self._regular_bytes(skill_root / "agents" / "openai.yaml", 16_384).decode("utf-8", errors="strict")
            )
            self.assertTrue(agent_metadata["policy"]["allow_implicit_invocation"])
            manifest = json.loads(
                self._regular_bytes(skill_root / "registries" / "reference-cards.manifest.json", 262_144).decode(
                    "utf-8", errors="strict"
                )
            )
            self.assertEqual(card_count, len(manifest["cards"]))
            matches = re.findall(
                rf"^- (?:frontier-engineering-plugin:)?{re.escape(skill)}:.*?\(file: ([^)]+)\)$",
                locator_text,
                flags=re.MULTILINE,
            )
            self.assertEqual(1, len(matches), skill)
            locator = Path(matches[0])
            self.assertNotIn("references", locator.parts)
            self.assertEqual(skill_path.resolve(strict=True), locator.resolve(strict=True))
            for card in manifest["cards"]:
                card_text = self._regular_bytes(skill_root / card["path"], 16_384).decode(
                    "utf-8", errors="strict"
                ).replace("\r\n", "\n")
                self.assertFalse(any(card_text in text for text in prompt_texts), card["path"])


if __name__ == "__main__":
    unittest.main()
