from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "skill-evaluator/scripts"))

from _bundle_hash import inventory, tree_hash  # noqa: E402
from _codex_eval_delivery import isolated_tool_schema_hash  # noqa: E402
import _codex_eval_isolation as isolation  # noqa: E402
from codex_eval_host import (  # noqa: E402
    ADAPTER_SOURCE_FILES,
    ADAPTER_VERSION,
    adapter_source_hash,
)
from validate_eval_suite import (  # noqa: E402
    load_v5_schema_registry,
    validate_host_protocol_record,
)
from skill_evaluator_test_support import (  # noqa: E402
    SkillEvaluatorTestCase,
    canonical_hash,
    materialize_v5_contract_fixture,
    rebind_v5_contract_fixture,
    runner_worst_case_attempt_budget,
)


ADAPTER = REPOSITORY_ROOT / "scripts/codex_eval_host.py"
EVENTS = REPOSITORY_ROOT / "scripts/_codex_eval_events.py"
CASES = REPOSITORY_ROOT / "tests/fixtures/model_evolution/codex-exec-cases.json"
MODEL = "fixture-model"
THREAD_ID = "019aa111-1111-7111-8111-111111111111"


FAKE_CODEX_SOURCE = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json
    import os
    from pathlib import Path
    import signal
    import sys
    import time

    executable = Path(__file__).resolve()
    config = json.loads(Path(str(executable) + ".json").read_text(encoding="utf-8"))
    state = Path(config["state"])
    previous = state.read_text(encoding="utf-8").splitlines() if state.exists() else []
    call_index = len(previous)
    prompt = sys.stdin.read()
    with state.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "argv": sys.argv[1:], "cwd": str(Path.cwd()), "prompt": prompt,
            "pwd": os.environ.get("PWD"), "oldpwd": os.environ.get("OLDPWD"),
        }) + "\\n")

    stderr = config.get("stderr")
    if stderr:
        sys.stderr.write(stderr)
    for line in config.get("stdout_lines", []):
        print(line, flush=True)
    mode = config.get("mode", "normal")
    if mode == "timeout":
        time.sleep(config.get("sleep_seconds", 5))
    if mode == "signal":
        os.kill(os.getpid(), signal.SIGTERM)
    if mode == "nonzero":
        raise SystemExit(config.get("exit_code", 7))
    if "raw_lines" in config:
        for line in config["raw_lines"]:
            print(line, flush=True)
        raise SystemExit(0)

    turns = config.get("turns") or [{}]
    turn = turns[min(call_index, len(turns) - 1)]
    if turn.get("sleep_seconds"):
        time.sleep(turn["sleep_seconds"])
    message = turn.get("message", "fixture complete")
    if "--output-schema" in sys.argv:
        message = json.dumps(config["grade"], separators=(",", ":"))
    if "--output-last-message" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
        output.write_text(message, encoding="utf-8")
    records = turn.get("records") or [
        {"type": "thread.started", "thread_id": config["thread_id"]},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {
            "id": f"message-{call_index}", "type": "agent_message", "text": message,
        }},
        {"type": "turn.completed", "usage": {
            "input_tokens": 10 + call_index, "output_tokens": 3,
        }},
    ]
    for record in records:
        print(json.dumps(record, separators=(",", ":")), flush=True)
    """
)


def _sha256_file(path: Path) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _grade_payload(batch: dict[str, object]) -> dict[str, object]:
    import hashlib

    prompt = "Judge the blinded fixture evidence.\n"
    prompt_hash = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()
    return {
        "grader_id": "fixture-grader",
        "batch_hash": "sha256:" + "1" * 64,
        "schedule_hash": "sha256:" + "2" * 64,
        "grader_prompt": prompt,
        "grader_prompt_hash": prompt_hash,
        "grader_schema_hash": "sha256:" + "3" * 64,
        "blinded_input": batch,
    }


def _tree_hash(root: Path) -> str:
    members = [path for path in root.rglob("*") if path.is_file() or path.is_symlink()]
    return tree_hash(inventory(root, members))


def _materialize_plugin(root: Path) -> tuple[Path, str]:
    plugin = root / "plugin"
    skill = plugin / "skills/writing-plans"
    skill.mkdir(parents=True)
    (plugin / ".codex-plugin").mkdir()
    (plugin / ".codex-plugin/plugin.json").write_text("{}\n", encoding="utf-8")
    body = "---\nname: writing-plans\ndescription: Fixture planner.\n---\nUse exact anchors.\n"
    (skill / "SKILL.md").write_text(body, encoding="utf-8")
    return plugin, body


def _plugin_bound_manifest(path: Path, fake: Path, plugin: Path, *, mode: str = "host") -> dict:
    manifest = _host_manifest(path, fake, mode=mode, sandbox="read-only")
    entry = manifest["catalog"]["entries"][0]
    entry.update({"id": "writing-plans", "name": "Writing Plans", "root_hash": _tree_hash(plugin / "skills/writing-plans")})
    manifest["catalog"]["catalog_hash"] = canonical_hash([entry])
    manifest["identity"]["execution"]["catalog_hash"] = manifest["catalog"]["catalog_hash"]
    manifest["identity"]["execution"]["skill_hash"] = _tree_hash(plugin)
    manifest["command"]["argv"].extend(["--plugin-root", str(plugin)])
    manifest["manifest_hash"] = canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _run_bound_adapter(
    workspace: Path, manifest: dict, request: dict
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        manifest["command"]["argv"],
        cwd=workspace,
        input=json.dumps(request, separators=(",", ":")) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )


def _load_events_module():
    spec = importlib.util.spec_from_file_location("codex_eval_events_test", EVENTS)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load Codex event normalizer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fake_codex(root: Path, **overrides: object) -> tuple[Path, Path]:
    fake = root / "fake-codex"
    state = root / "fake-codex.calls.jsonl"
    fake.write_text(FAKE_CODEX_SOURCE, encoding="utf-8")
    fake.chmod(0o755)
    config = {
        "state": str(state),
        "thread_id": THREAD_ID,
        "mode": "normal",
        "turns": [],
        **overrides,
    }
    Path(str(fake) + ".json").write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
    )
    return fake, state


def _bound_adapter_argv(
    fake: Path,
    manifest: Path,
    *,
    mode: str = "host",
    timeout: float = 2,
    profile: str = "fixture-profile",
    sandbox: str = "workspace-write",
) -> list[str]:
    return [
        sys.executable,
        str(ADAPTER),
        "--mode",
        mode,
        "--codex",
        str(fake),
        "--codex-sha256",
        _sha256_file(fake),
        "--codex-version",
        "0.0.0",
        "--host-manifest",
        str(manifest),
        "--model",
        MODEL,
        "--effort",
        "high",
        "--profile",
        profile,
        "--sandbox",
        sandbox,
        "--timeout",
        str(timeout),
    ]


def _host_manifest(
    path: Path,
    fake: Path,
    *,
    mode: str = "host",
    timeout: float = 2,
    profile: str = "fixture-profile",
    sandbox: str = "workspace-write",
) -> dict:
    manifest = json.loads(
        (
            REPOSITORY_ROOT / "tests/fixtures/skill_evaluator/host-manifest-v1.json"
        ).read_text(encoding="utf-8")
    )
    manifest["identity"]["adapter"].update(
        {
            "id": "codex-eval-host",
            "version": ADAPTER_VERSION,
            "sha256": adapter_source_hash(),
        }
    )
    manifest["identity"]["repository"]["worktree"] = str(path.parent.resolve())
    manifest["identity"]["execution"]["model"] = MODEL
    manifest["identity"]["host_build"] = _sha256_file(fake)
    manifest["identity"]["host_version"] = "0.0.0"
    manifest["identity"]["execution"]["harness"] = (
        f"codex-cli-0.0.0-effort-high-profile-{profile}-tier-default"
    )
    manifest["identity"]["execution"]["model_revision"] = (
        "codex-catalog-0.0.0-sha256:" + "1" * 64
    )
    manifest["identity"]["execution"]["tool_schema_hash"] = (
        isolated_tool_schema_hash(_sha256_file(fake))
    )
    manifest["command"].update(
        {
            "argv": _bound_adapter_argv(
                fake,
                path,
                mode=mode,
                timeout=timeout,
                profile=profile,
                sandbox=sandbox,
            ),
            "resolved_executable": str(Path(sys.executable).resolve()),
            "executable_sha256": _sha256_file(Path(sys.executable).resolve()),
        }
    )
    manifest["manifest_hash"] = canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    )
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _materialize_adapter_fixture(root: Path, fake: Path) -> dict[str, Path]:
    paths = materialize_v5_contract_fixture(root)
    host = json.loads(paths["host"].read_text(encoding="utf-8"))
    host["identity"]["adapter"].update(
        {
            "id": "codex-eval-host",
            "version": ADAPTER_VERSION,
            "sha256": adapter_source_hash(),
        }
    )
    host["identity"]["repository"]["worktree"] = str(root.resolve())
    host["identity"]["execution"]["model"] = MODEL
    host["identity"]["host_build"] = _sha256_file(fake)
    host["identity"]["host_version"] = "0.0.0"
    host["identity"]["execution"]["harness"] = (
        "codex-cli-0.0.0-effort-high-profile-fixture-profile-tier-default"
    )
    host["identity"]["execution"]["model_revision"] = (
        "codex-catalog-0.0.0-sha256:" + "1" * 64
    )
    host["identity"]["execution"]["tool_schema_hash"] = (
        isolated_tool_schema_hash(_sha256_file(fake))
    )
    host["command"].update(
        {
            "argv": _bound_adapter_argv(fake, paths["host"]),
            "resolved_executable": str(Path(sys.executable).resolve()),
            "executable_sha256": _sha256_file(Path(sys.executable).resolve()),
        }
    )
    paths["host"].write_text(json.dumps(host, indent=2) + "\n", encoding="utf-8")
    rebind_v5_contract_fixture(paths)
    return paths


def _request(kind: str, payload: dict) -> dict:
    request = {
        "record_type": "skill-evaluator-host-request/1",
        "request_hash": "",
        "envelope": {
            "attempt": 1,
            "entry_id": "entry-fixture",
            "entry_ordinal": 0,
            "plan_hash": "sha256:" + "1" * 64,
            "plan_id": "plan-fixture",
            "request_kind": kind,
            "run_id": "run-fixture",
        },
        "payload": payload,
    }
    request["request_hash"] = canonical_hash(
        {key: value for key, value in request.items() if key != "request_hash"}
    )
    return request


def _execute_payload(turn_count: int = 1) -> dict:
    return {
        "case": {
            "case_id": "case-codex",
            "timeout_seconds": 5,
            "state_model": {"scope": "none"},
            "requirements": [
                {
                    "requirement_id": "outcome",
                    "owner": "deterministic",
                }
            ],
        },
        "turns": [
            {
                "turn_id": f"turn-{index + 1}",
                "input": {
                    "kind": "user_message",
                    "content": f"fixture turn {index + 1}",
                },
                "checkpoint": "final" if index + 1 == turn_count else "intermediate",
                "open_obligations": ["outcome"],
                "due_obligations": ["outcome"] if index + 1 == turn_count else [],
            }
            for index in range(turn_count)
        ],
        "execution_context": {
            "expected_principal_slots": ["lead"],
            "expected_tools": [],
        },
        "permission_policy": "sha256:" + "a" * 64,
        "fault_script": [],
        "coordination": None,
    }


def _adapter_argv(
    fake: Path,
    manifest: Path,
    *,
    mode: str = "host",
    timeout: float = 2,
    profile: str = "fixture-profile",
) -> list[str]:
    return _bound_adapter_argv(
        fake,
        manifest,
        mode=mode,
        timeout=timeout,
        profile=profile,
    )


def _run_adapter(
    workspace: Path,
    fake: Path,
    manifest: Path,
    request: dict,
    *,
    mode: str = "host",
    timeout: float = 2,
    profile: str = "fixture-profile",
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    child_environment = dict(os.environ)
    child_environment.update(environment or {})
    return subprocess.run(
        _adapter_argv(
            fake,
            manifest,
            mode=mode,
            timeout=timeout,
            profile=profile,
        ),
        cwd=workspace,
        input=json.dumps(request, separators=(",", ":")) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=max(timeout + 2, 4),
        env=child_environment,
    )


def _jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line]


class TestCodexEventNormalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.events = _load_events_module()
        cls.cases = json.loads(CASES.read_text(encoding="utf-8"))

    def test_fixture_table_preserves_direct_facts_and_diagnostics(self) -> None:
        for case in self.cases["normalization_cases"]:
            with self.subTest(case=case["id"]):
                if "raw_lines" in case:
                    raw = ("\n".join(case["raw_lines"]) + "\n").encode()
                else:
                    raw = b"".join(
                        json.dumps(record, separators=(",", ":")).encode() + b"\n"
                        for record in case["records"]
                    )
                actual = self.events.normalize_jsonl(raw)
                expected = case["expected"]
                self.assertEqual(expected["status"], actual["status"])
                if actual["status"] == "protocol_error":
                    self.assertEqual(
                        expected["diagnostic_kind"],
                        actual["diagnostics"][0]["kind"],
                    )
                    if "diagnostic_message" in expected:
                        self.assertEqual(
                            expected["diagnostic_message"],
                            actual["diagnostics"][0]["message"],
                        )
                    continue
                for field in (
                    "thread_id",
                    "final_message",
                    "tool_call_ids",
                    "permission_denials",
                    "usage",
                ):
                    self.assertEqual(expected[field], actual[field], field)
                if "failures" in expected:
                    self.assertEqual(expected["failures"], actual["failures"])

    def test_current_item_update_preserves_a_live_item(self) -> None:
        records = [
            {"type": "thread.started", "thread_id": THREAD_ID},
            {"type": "turn.started"},
            {
                "type": "item.started",
                "item": {"id": "todo-1", "type": "todo_list", "items": []},
            },
            {
                "type": "item.updated",
                "item": {
                    "id": "todo-1",
                    "type": "todo_list",
                    "items": [{"text": "inspect", "completed": True}],
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "todo-1",
                    "type": "todo_list",
                    "items": [{"text": "inspect", "completed": True}],
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 10}},
        ]
        normalized = self.events.normalize_records(records)
        self.assertEqual("completed", normalized["status"])
        self.assertEqual(
            ["started", "updated", "completed"],
            [item["phase"] for item in normalized["items"]],
        )

        invalid = self.events.normalize_records(
            [records[0], records[1], records[3], records[-1]],
        )
        self.assertEqual("protocol_error", invalid["status"])
        self.assertEqual(
            "Codex item updated before start",
            invalid["diagnostics"][0]["message"],
        )

        incomplete = self.events.normalize_records(
            [records[0], records[1], records[2], records[-1]],
        )
        self.assertEqual("protocol_error", incomplete["status"])
        self.assertEqual(
            "Codex stream has incomplete items: stdout record 3 "
            "(item.started/todo_list)",
            incomplete["diagnostics"][0]["message"],
        )

        invalid_cases = (
            (
                [
                    records[0],
                    records[1],
                    records[2],
                    records[4],
                    records[3],
                    records[-1],
                ],
                "Codex item updated after completion",
            ),
            (
                [
                    records[0],
                    records[1],
                    records[2],
                    {
                        "type": "item.updated",
                        "item": {
                            "id": "todo-1",
                            "type": "agent_message",
                            "text": "changed",
                        },
                    },
                    records[-1],
                ],
                "Codex item type changed across its lifecycle",
            ),
        )
        for invalid_records, expected_message in invalid_cases:
            with self.subTest(expected_message=expected_message):
                invalid = self.events.normalize_records(invalid_records)
                self.assertEqual("protocol_error", invalid["status"])
                self.assertEqual(
                    expected_message,
                    invalid["diagnostics"][0]["message"],
                )

    def test_current_exec_items_and_single_principal_boundary(self) -> None:
        records = [
            {"type": "thread.started", "thread_id": THREAD_ID},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "warning-1",
                    "type": "error",
                    "message": "write denied by the read-only sandbox",
                },
            },
            {
                "type": "item.completed",
                "item": {"id": "todo-1", "type": "todo_list", "items": []},
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "collab-1",
                    "type": "collab_tool_call",
                    "tool": "spawn_agent",
                    "status": "completed",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "id": "message-1",
                    "type": "agent_message",
                    "text": "done",
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 10}},
        ]
        raw = b"".join(
            json.dumps(record, separators=(",", ":")).encode() + b"\n"
            for record in records
        )
        normalized = self.events.normalize_jsonl(raw)
        self.assertEqual("completed", normalized["status"])
        self.assertEqual(
            ["error", "todo_list", "collab_tool_call", "agent_message"],
            [item["type"] for item in normalized["items"]],
        )
        self.assertEqual(
            "write denied by the read-only sandbox",
            normalized["failures"][0]["message"],
        )
        payload = {
            "coordination": None,
            "fault_script": [],
            "execution_context": {
                "expected_principal_slots": ["main"],
                "expected_tools": [],
            },
            "case": {"state_model": {"scope": "none"}},
        }
        diagnostics = self.events.execute_evidence_diagnostics(
            payload, [normalized]
        )
        self.assertEqual(1, len(diagnostics))
        self.assertIn("outside the single-principal contract", diagnostics[0]["message"])

    def test_model_grade_schema_uses_provider_supported_array_shape(self) -> None:
        batch = {
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-1",
                    "checks": [{"id": "check-a"}, {"id": "check-b"}],
                },
                {
                    "item_id": "item-2",
                    "checks": [{"id": "check-a"}, {"id": "check-b"}],
                },
            ],
        }
        schema = self.events.model_grade_schema(batch)
        self.assertEqual({"items"}, set(schema["properties"]))
        items = schema["properties"]["items"]
        checks = items["items"]["properties"]["checks"]
        self.assertNotIn("prefixItems", json.dumps(schema))
        self.assertEqual((2, 2), (items["minItems"], items["maxItems"]))
        self.assertEqual((2, 2), (checks["minItems"], checks["maxItems"]))
        output = {
            "items": [
                {
                    "checks": [
                        {
                            "pass": True,
                            "notes": f"item-{item_number}",
                            "uncertainty": "none",
                        }
                        for _ in ("check-a", "check-b")
                    ],
                }
                for item_number in (1, 2)
            ],
        }
        bound, diagnostics = self.events.bind_model_grade_output(output, batch)
        self.assertEqual([], diagnostics)
        self.assertEqual("batch-1", bound["batch_id"])
        self.assertEqual(
            ["item-1", "item-2"],
            [item["item_id"] for item in bound["items"]],
        )
        self.assertEqual(
            ["check-a", "check-b"],
            [item["id"] for item in bound["items"][0]["checks"]],
        )
        output["items"][1]["item_id"] = "outside-bound-batch"
        bound, diagnostics = self.events.bind_model_grade_output(output, batch)
        self.assertIsNone(bound)
        self.assertEqual("identity_mismatch", diagnostics[0]["kind"])


class TestCodexEvalHostProcess(SkillEvaluatorTestCase):
    def test_bubblewrap_exposes_only_workspace_and_request_state(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory(
                prefix="frontier-isolation-test-", dir="/dev/shm"
            ) as codex_home_name,
            tempfile.TemporaryDirectory(
                prefix="frontier-private-home-test-", dir=Path.home()
            ) as private_home_name,
        ):
            canonical = Path(tmp) / "Frontier-Agent-skills"
            source = canonical / ".worktrees/source"
            workspace = canonical / ".work/campaign/workspace"
            output = Path(tmp) / "output"
            executable_dir = source / "bin"
            for path in (workspace, output, executable_dir):
                path.mkdir(parents=True)
            (source / "secret.txt").write_text("source-only\n", encoding="utf-8")
            private_home_secret = Path(private_home_name) / "secret.txt"
            private_home_secret.write_text("home-only\n", encoding="utf-8")
            (workspace / "fixture.txt").write_text("workspace-only\n", encoding="utf-8")
            fake = executable_dir / "fake-codex"
            global_codex_auth = Path.home() / ".codex/auth.json"
            fake.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env python3
                    import json
                    import os
                    from pathlib import Path
                    import subprocess

                    assert Path({str(source / 'secret.txt')!r}).exists() is False
                    assert Path({str(private_home_secret)!r}).exists() is False
                    assert Path({str(global_codex_auth)!r}).exists() is False
                    assert Path('/run/frontier-codex-home/auth.json').is_file()
                    assert Path('/run/frontier-codex-bin/codex-code-mode-host').is_file()
                    assert Path('/tmp/frontier-workspace/fixture.txt').read_text() == 'workspace-only\\n'
                    processes = subprocess.check_output(['ps', '-eo', 'args='], text=True)
                    assert {str(source)!r} not in processes
                    Path('/tmp/frontier-output/proof.json').write_text(json.dumps({{
                        'codex_home': os.environ.get('CODEX_HOME'),
                        'cwd': str(Path.cwd()),
                        'home': os.environ.get('HOME'),
                        'oldpwd': os.environ.get('OLDPWD'),
                        'pwd': os.environ.get('PWD'),
                    }}), encoding='utf-8')
                    """
                ),
                encoding="utf-8",
            )
            fake.chmod(0o700)
            code_mode_host = fake.with_name("codex-code-mode-host")
            shutil.copyfile(fake, code_mode_host)
            code_mode_host.chmod(0o700)
            isolation_name = shutil.which("bwrap")
            self.assertIsNotNone(isolation_name)
            assert isolation_name is not None
            isolation_tool = Path(isolation_name).resolve(strict=True)
            args = argparse.Namespace(
                codex=fake.resolve(strict=True),
                isolation_tool=isolation_tool,
                sandbox="read-only",
                source_root=source.resolve(strict=True),
            )
            last_message = output / "last-message.txt"
            argv = isolation.isolated_child_argv(
                isolation_tool=args.isolation_tool,
                sandbox=args.sandbox,
                source_root=args.source_root,
                codex=args.codex,
                code_mode_host=code_mode_host.resolve(strict=True),
                argv=[
                    str(fake),
                    "--cd",
                    str(workspace),
                    "--output-last-message",
                    str(last_message),
                ],
                workspace=workspace.resolve(strict=True),
                codex_home=Path(codex_home_name),
            )
            environment = os.environ.copy()
            environment["PWD"] = "/tmp/frontier-workspace"
            environment.pop("OLDPWD", None)
            result = subprocess.run(
                argv,
                cwd=workspace,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            proof = json.loads((output / "proof.json").read_text(encoding="utf-8"))
            self.assertEqual("/run/frontier-codex-home", proof["codex_home"])
            self.assertEqual("/tmp/frontier-workspace", proof["cwd"])
            self.assertEqual("/run/frontier-home", proof["home"])
            self.assertIsNone(proof["oldpwd"])
            self.assertEqual("/tmp/frontier-workspace", proof["pwd"])
            self.assertEqual("source-only\n", (source / "secret.txt").read_text())

    def test_adapter_identity_covers_runtime_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp)
            for name in ADAPTER_SOURCE_FILES:
                source = REPOSITORY_ROOT / "scripts" / name
                (scripts / name).write_bytes(source.read_bytes())
            self.assertEqual(adapter_source_hash(), adapter_source_hash(scripts))
            events = scripts / "_codex_eval_events.py"
            events.write_bytes(events.read_bytes() + b"\n# identity drift\n")
            self.assertNotEqual(adapter_source_hash(), adapter_source_hash(scripts))

    def test_completed_turn_without_usage_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            fake, _ = _write_fake_codex(
                root,
                turns=[{
                    "records": [
                        {"type": "thread.started", "thread_id": THREAD_ID},
                        {"type": "turn.started"},
                        {"type": "item.completed", "item": {
                            "id": "message-0",
                            "type": "agent_message",
                            "text": "fixture complete",
                        }},
                        {"type": "turn.completed"},
                    ],
                }],
            )
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake)
            result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", _execute_payload()),
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("lacks captured token usage", result.stderr)

    def test_execute_uses_exact_session_resume_and_safe_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            fake, state = _write_fake_codex(root)
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake)
            result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", _execute_payload(2)),
            )
            self.assertEqual(0, result.returncode, result.stderr)
            records = _jsonl(result.stdout)
            self.assertEqual(
                ["skill-evaluator-host-event/1"] * 2
                + ["skill-evaluator-host-result/1"],
                [record["record_type"] for record in records],
            )
            self.assertEqual("completed", records[-1]["terminal_status"])
            self.assertEqual(
                [],
                validate_host_protocol_record(
                    "host_result", records[-1], load_v5_schema_registry()
                ),
            )
            self.assertEqual(THREAD_ID, records[-1]["principals"][0]["session_id"])
            self.assertEqual(
                10, records[0]["payload"]["codex"]["usage"]["input_tokens"]
            )
            self.assertEqual("captured", records[-1]["context"]["status"])
            self.assertEqual(0, records[-1]["context"]["controlled_bytes"])
            self.assertEqual(
                [10, 11],
                [row["input_tokens"] for row in records[-1]["usage"]["records"]],
            )
            calls = _jsonl(state.read_text(encoding="utf-8"))
            self.assertEqual(2, len(calls))
            self.assertNotIn("resume", calls[0]["argv"])
            self.assertEqual(
                ["exec", "resume"],
                [calls[1]["argv"][0], calls[1]["argv"][1]],
            )
            self.assertIn(THREAD_ID, calls[1]["argv"])
            flattened = [argument for call in calls for argument in call["argv"]]
            for forbidden in (
                "--last",
                "--dangerously-bypass-approvals-and-sandbox",
                "--search",
                "--full-auto",
            ):
                self.assertNotIn(forbidden, flattened)
            self.assertIn(MODEL, flattened)
            self.assertIn('model_reasoning_effort="high"', flattened)
            for call in calls:
                self.assertIn("--profile", call["argv"])
                self.assertIn("fixture-profile", call["argv"])
            artifacts = records[-1]["artifacts"]
            self.assertEqual(1, len(artifacts))
            self.assertTrue((workspace / Path(artifacts[0]["path"]).name).is_file())
            self.assertEqual(
                [Path(artifacts[0]["path"]).name],
                sorted(path.name for path in workspace.iterdir()),
            )

    def test_model_grader_receives_hash_bound_fixture_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            fixture = workspace / "fixtures/source.md"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("Bound source fact.\n", encoding="utf-8")
            fake, state = _write_fake_codex(root)
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake)
            payload = _execute_payload()
            payload["case"]["requirements"].append(
                {"requirement_id": "quality", "owner": "model"}
            )
            payload["case"]["fixture"] = {
                "initial_files": [{
                    "path": "fixtures/source.md",
                    "sha256": _sha256_file(fixture),
                }]
            }

            result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", payload),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            terminal = _jsonl(result.stdout)[-1]
            evidence_record = next(
                item for item in terminal["artifacts"]
                if "workspace-evidence-" in item["path"]
            )
            evidence = json.loads(
                (workspace / Path(evidence_record["path"]).name).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                {"fixtures/source.md": "Bound source fact.\n"},
                evidence["initial_files"],
            )
            observation_record = next(
                item for item in terminal["artifacts"]
                if "host-observation-" in item["path"]
            )
            observation = json.loads(
                (workspace / Path(observation_record["path"]).name).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                ["fixtures/source.md"], observation["protected_paths"]
            )

            fixture.write_text("tampered\n", encoding="utf-8")
            rejected = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", payload),
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("fixture hash differs", rejected.stderr)
            self.assertEqual(1, len(_jsonl(state.read_text(encoding="utf-8"))))

    def test_each_turn_receives_the_full_bound_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            fake, state = _write_fake_codex(
                root,
                turns=[{"sleep_seconds": 0.65}, {"sleep_seconds": 0.65}],
            )
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake, timeout=1)

            result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", _execute_payload(2)),
                timeout=1,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(2, len(_jsonl(state.read_text(encoding="utf-8"))))
            records = _jsonl(result.stdout)
            self.assertEqual(3, len(records))
            self.assertEqual("completed", records[-1]["terminal_status"])

    def test_default_profile_sentinel_is_omitted_on_fresh_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            fake, state = _write_fake_codex(root)
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake, profile="none")
            result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", _execute_payload(2)),
                profile="none",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            calls = _jsonl(state.read_text(encoding="utf-8"))
            self.assertEqual(2, len(calls))
            for call in calls:
                self.assertNotIn("--profile", call["argv"])

    def test_bound_plugin_delivers_force_loaded_treatment_and_isolates_catalog(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            plugin, body = _materialize_plugin(root)
            fake, state = _write_fake_codex(root)
            manifest_path = root / "host.json"
            manifest = _plugin_bound_manifest(manifest_path, fake, plugin)

            candidate = _execute_payload()
            candidate.update(
                {
                    "subject_skill_id": "writing-plans",
                    "catalog": manifest["catalog"]["entries"],
                    "treatment": {"profile": "candidate/force_loaded"},
                }
            )
            candidate_workspace = root / "candidate"
            candidate_workspace.mkdir()
            result = _run_bound_adapter(
                candidate_workspace,
                manifest,
                _request("execute_case", candidate),
            )
            self.assertEqual(0, result.returncode, result.stderr)
            terminal = _jsonl(result.stdout)[-1]
            self.assertEqual(
                [],
                validate_host_protocol_record(
                    "host_result", terminal, load_v5_schema_registry()
                ),
            )
            self.assertEqual(len(body.encode()), terminal["context"]["bytes"])
            self.assertEqual(
                "skills/writing-plans/SKILL.md",
                terminal["context"]["components"][0]["source_path"],
            )
            component = terminal["context"]["components"][0]
            artifact = candidate_workspace / Path(
                component["artifact"]["path"]
            ).name
            self.assertEqual(body, artifact.read_text(encoding="utf-8"))
            self.assertEqual(
                component["content_sha256"], _sha256_file(artifact)
            )
            call = _jsonl(state.read_text(encoding="utf-8"))[0]
            self.assertIn(body, call["prompt"])
            self.assertIn("fixture turn 1", call["prompt"])
            child_workspace = Path(call["cwd"])
            self.assertNotEqual(candidate_workspace.resolve(), child_workspace)
            self.assertNotIn(root.resolve(), child_workspace.parents)
            self.assertEqual(call["cwd"], call["pwd"])
            self.assertIsNone(call["oldpwd"])
            cd_index = call["argv"].index("--cd")
            self.assertEqual(str(child_workspace), call["argv"][cd_index + 1])
            disabled = [
                call["argv"][index + 1]
                for index, value in enumerate(call["argv"][:-1])
                if value == "--disable"
            ]
            self.assertEqual(
                ["plugins", "multi_agent", "multi_agent_v2"], disabled
            )
            self.assertFalse((candidate_workspace / ".git").exists())
            self.assertFalse(
                (candidate_workspace / ".agents/skills/writing-plans").exists()
            )
            omitted = subprocess.run(
                manifest["command"]["argv"][:-2],
                cwd=candidate_workspace,
                input=json.dumps(_request("execute_case", candidate)) + "\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
            self.assertEqual(2, omitted.returncode)
            self.assertIn("omitted", omitted.stderr)

            baseline = json.loads(json.dumps(candidate))
            baseline["treatment"]["profile"] = "baseline/skill_disabled"
            baseline_workspace = root / "baseline"
            baseline_workspace.mkdir()
            result = _run_bound_adapter(
                baseline_workspace,
                manifest,
                _request("execute_case", baseline),
            )
            self.assertEqual(0, result.returncode, result.stderr)
            terminal = _jsonl(result.stdout)[-1]
            self.assertEqual(0, terminal["context"]["controlled_bytes"])
            self.assertEqual([], terminal["context"]["components"])
            call = _jsonl(state.read_text(encoding="utf-8"))[1]
            self.assertNotIn(body, call["prompt"])
            self.assertEqual("fixture turn 1", call["prompt"])

    def test_bound_plugin_tamper_and_probe_child_failure_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin, _ = _materialize_plugin(root)
            fake, state = _write_fake_codex(
                root,
                mode="nonzero",
                stdout_lines=[
                    json.dumps(
                        {
                            "type": "error",
                            "message": "You've hit your usage limit. Try again later.",
                        }
                    )
                ],
            )
            manifest_path = root / "probe-host.json"
            manifest = _plugin_bound_manifest(
                manifest_path,
                fake,
                plugin,
                mode="probe",
            )
            workspace = root / "probe"
            workspace.mkdir()
            probe = {
                "schema_version": "codex-interaction-probe/1.0",
                "probe_id": "probe-force-load",
                "capability": "force_load",
                "prompt": "$writing-plans produce a plan",
                "expected_event_types": ["thread.started", "turn.completed"],
            }
            result = _run_bound_adapter(workspace, manifest, probe)
            self.assertEqual(0, result.returncode, result.stderr)
            terminal = _jsonl(result.stdout)[0]
            self.assertEqual("unknown", terminal["status"])
            self.assertEqual(
                "provider_usage_limit", terminal["diagnostics"][0]["kind"]
            )
            self.assertEqual(
                "Codex provider usage limit reached",
                terminal["diagnostics"][0]["message"],
            )

            (plugin / "skills/writing-plans/SKILL.md").write_text(
                "tampered\n",
                encoding="utf-8",
            )
            rejected_workspace = root / "rejected"
            rejected_workspace.mkdir()
            rejected = _run_bound_adapter(rejected_workspace, manifest, probe)
            self.assertEqual(2, rejected.returncode)
            self.assertIn("plugin Skill bytes differ", rejected.stderr)
            self.assertEqual(1, len(_jsonl(state.read_text(encoding="utf-8"))))

    def test_bound_plugin_allows_staging_path_outside_source_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            campaign = root / "campaign"
            campaign.mkdir()
            plugin, _ = _materialize_plugin(campaign / "staging")
            records = [
                {"type": "thread.started", "thread_id": THREAD_ID},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {
                        "id": "command-read-staged-skill",
                        "type": "command_execution",
                        "command": "rtk read staged/SKILL.md",
                        "aggregated_output": str(plugin / "skills/writing-plans/SKILL.md"),
                        "exit_code": 0,
                        "status": "completed",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-1",
                        "type": "agent_message",
                        "text": "fixture complete",
                    },
                },
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 10, "output_tokens": 3},
                },
            ]
            fake, _ = _write_fake_codex(root, turns=[{"records": records}])
            manifest_path = campaign / "host.json"
            manifest = _plugin_bound_manifest(manifest_path, fake, plugin)
            manifest["identity"]["repository"]["worktree"] = str(source)
            manifest["manifest_hash"] = canonical_hash(
                {key: value for key, value in manifest.items() if key != "manifest_hash"}
            )
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            candidate = _execute_payload()
            candidate.update({
                "subject_skill_id": "writing-plans",
                "catalog": manifest["catalog"]["entries"],
                "treatment": {"profile": "candidate/force_loaded"},
            })
            workspace = root / "workspace"
            workspace.mkdir()

            result = _run_bound_adapter(
                workspace, manifest, _request("execute_case", candidate)
            )

            self.assertEqual(0, result.returncode, result.stderr)
            terminal = _jsonl(result.stdout)[-1]
            self.assertEqual("completed", terminal["terminal_status"])
            self.assertIsNone(terminal["protocol_error"])

    def test_bound_plugin_rejects_source_repository_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            plugin, _ = _materialize_plugin(root)
            fake, _ = _write_fake_codex(root, turns=[{"message": str(root)}])
            manifest_path = root / "host.json"
            manifest = _plugin_bound_manifest(manifest_path, fake, plugin)
            candidate = _execute_payload()
            candidate.update({
                "subject_skill_id": "writing-plans",
                "catalog": manifest["catalog"]["entries"],
                "treatment": {"profile": "candidate/force_loaded"},
            })
            workspace = root / "workspace"
            workspace.mkdir()

            result = _run_bound_adapter(
                workspace, manifest, _request("execute_case", candidate)
            )

            self.assertEqual(0, result.returncode, result.stderr)
            terminal = _jsonl(result.stdout)[-1]
            self.assertEqual("protocol_error", terminal["terminal_status"])
            protocol = json.dumps(terminal["protocol_error"])
            self.assertIn("stdout record 3", protocol)
            self.assertIn("item.completed/agent_message", protocol)
            self.assertIn("/item/text", protocol)
            self.assertNotIn(str(root), protocol)

    def test_bound_plugin_redacts_source_repository_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            plugin, _ = _materialize_plugin(root)
            fake, _ = _write_fake_codex(root, stderr=str(root))
            manifest_path = root / "host.json"
            manifest = _plugin_bound_manifest(manifest_path, fake, plugin)
            candidate = _execute_payload()
            candidate.update({
                "subject_skill_id": "writing-plans",
                "catalog": manifest["catalog"]["entries"],
                "treatment": {"profile": "candidate/force_loaded"},
            })
            workspace = root / "workspace"
            workspace.mkdir()

            result = _run_bound_adapter(
                workspace, manifest, _request("execute_case", candidate)
            )

            self.assertEqual(0, result.returncode)
            terminal = _jsonl(result.stdout)[-1]
            protocol = json.dumps(terminal["protocol_error"])
            self.assertEqual("protocol_error", terminal["terminal_status"])
            self.assertIn("stderr record 1 (unstructured)", protocol)
            self.assertNotIn(str(root), protocol)
            self.assertIn("<source-repository>", result.stderr)
            self.assertNotIn(str(root), result.stderr)

    def test_bound_plugin_projects_observed_skill_read_and_sandbox_denial(self) -> None:
        cases = (
            (
                "natural_routing",
                "produce a repository plan",
                {
                    "id": "command-read-skill",
                    "type": "command_execution",
                    "command": "rtk read .agents/skills/writing-plans/SKILL.md",
                    "aggregated_output": "skill body",
                    "exit_code": 0,
                    "status": "completed",
                },
                "direct.routing",
            ),
            (
                "action_authorization_trace",
                "attempt a denied write",
                {
                    "id": "command-denied",
                    "type": "command_execution",
                    "command": "touch probe-output.txt",
                    "aggregated_output": "Read-only file system",
                    "exit_code": 1,
                    "status": "failed",
                },
                "permission.denied",
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin, _ = _materialize_plugin(root)
            for capability, prompt, command, direct in cases:
                with self.subTest(capability=capability):
                    case_root = root / capability
                    case_root.mkdir()
                    records = [
                        {"type": "thread.started", "thread_id": THREAD_ID},
                        {"type": "turn.started"},
                        {"type": "item.completed", "item": command},
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "message-1",
                                "type": "agent_message",
                                "text": "fixture complete",
                            },
                        },
                        {
                            "type": "turn.completed",
                            "usage": {"input_tokens": 10, "output_tokens": 3},
                        },
                    ]
                    fake, _ = _write_fake_codex(
                        case_root,
                        turns=[{"records": records}],
                    )
                    manifest = _plugin_bound_manifest(
                        case_root / "host.json",
                        fake,
                        plugin,
                        mode="probe",
                    )
                    workspace = case_root / "workspace"
                    workspace.mkdir()
                    probe = {
                        "schema_version": "codex-interaction-probe/1.0",
                        "probe_id": f"probe-{capability}",
                        "capability": capability,
                        "prompt": prompt,
                        "expected_event_types": [
                            "thread.started",
                            "turn.completed",
                            direct,
                        ],
                    }
                    result = _run_bound_adapter(workspace, manifest, probe)
                    self.assertEqual(0, result.returncode, result.stderr)
                    terminal = _jsonl(result.stdout)[0]
                    self.assertEqual("pass", terminal["status"])
                    self.assertIn(direct, terminal["direct_observations"])
                    self.assertEqual(
                        ["writing-plans"] if capability == "natural_routing" else [],
                        terminal["routing"],
                    )

            stderr_root = root / "stderr-denial"
            stderr_root.mkdir()
            fake, _ = _write_fake_codex(
                stderr_root,
                stderr=(
                    "patch rejected: writing is blocked by read-only sandbox; "
                    "rejected by user approval settings\n"
                ),
            )
            manifest = _plugin_bound_manifest(
                stderr_root / "host.json", fake, plugin, mode="probe"
            )
            workspace = stderr_root / "workspace"
            workspace.mkdir()
            probe = {
                "schema_version": "codex-interaction-probe/1.0",
                "probe_id": "probe-stderr-denial",
                "capability": "action_authorization_trace",
                "prompt": "attempt a denied write",
                "expected_event_types": [
                    "thread.started",
                    "turn.completed",
                    "permission.denied",
                ],
            }
            result = _run_bound_adapter(workspace, manifest, probe)
            self.assertEqual(0, result.returncode, result.stderr)
            terminal = _jsonl(result.stdout)[0]
            self.assertEqual("pass", terminal["status"])
            self.assertIn("permission.denied", terminal["direct_observations"])

    def test_model_grade_and_probe_use_closed_outputs(self) -> None:
        provider_grade = {
            "items": [{
                "checks": [{
                    "pass": True,
                    "notes": "fixture",
                    "uncertainty": "none",
                }],
            }],
        }
        bound_grade = {
            "batch_id": "batch-fixture",
            "items": [
                {
                    "item_id": "item-1",
                    "checks": [
                        {
                            "id": "check-1",
                            "pass": True,
                            "notes": "fixture",
                            "uncertainty": "none",
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            fake, state = _write_fake_codex(root, grade=provider_grade)
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake)
            batch = {
                "batch_id": "batch-fixture",
                "items": [
                    {
                        "item_id": "item-1",
                        "checks": [{"id": "check-1"}],
                    }
                ],
            }
            grade_result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("model_grade", _grade_payload(batch)),
            )
            self.assertEqual(0, grade_result.returncode, grade_result.stderr)
            grade_record = _jsonl(grade_result.stdout)[-1]
            self.assertEqual("completed", grade_record["terminal_status"])
            self.assertEqual(
                [],
                validate_host_protocol_record(
                    "host_result", grade_record, load_v5_schema_registry()
                ),
            )
            self.assertEqual(1, len(grade_record["artifacts"]))
            self.assertEqual(10, grade_record["usage"]["records"][0]["input_tokens"])
            artifact = workspace / Path(grade_record["artifacts"][0]["path"]).name
            self.assertEqual(bound_grade, json.loads(artifact.read_text(encoding="utf-8")))
            grade_call = _jsonl(state.read_text(encoding="utf-8"))[0]
            self.assertIn("--output-schema", grade_call["argv"])
            self.assertIn("Judge the blinded fixture evidence.", grade_call["prompt"])
            self.assertNotIn("treatment", grade_call["prompt"].lower())

            invalid_grade = json.loads(json.dumps(provider_grade))
            invalid_grade["items"][0]["item_id"] = "outside-bound-batch"
            fake_config_path = Path(str(fake) + ".json")
            fake_config = json.loads(fake_config_path.read_text(encoding="utf-8"))
            fake_config["grade"] = invalid_grade
            fake_config_path.write_text(
                json.dumps(fake_config, indent=2) + "\n",
                encoding="utf-8",
            )
            invalid_workspace = root / "invalid-grade-workspace"
            invalid_workspace.mkdir()
            invalid_result = _run_adapter(
                invalid_workspace,
                fake,
                manifest_path,
                _request("model_grade", _grade_payload(batch)),
            )
            self.assertEqual(0, invalid_result.returncode, invalid_result.stderr)
            invalid_record = _jsonl(invalid_result.stdout)[-1]
            self.assertEqual("protocol_error", invalid_record["terminal_status"])
            self.assertEqual("identity_mismatch", invalid_record["protocol_error"]["kind"])
            self.assertEqual(
                invalid_record["artifacts"][0],
                invalid_record["protocol_error"]["artifact"],
            )
            self.assertEqual(1, len(invalid_record["usage"]["records"]))

            tampered = _grade_payload(batch)
            tampered["grader_prompt"] = "Different instruction.\n"
            rejected = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("model_grade", tampered),
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("instruction identity is invalid", rejected.stderr)

            probe = {
                "schema_version": "codex-interaction-probe/1.0",
                "probe_id": "probe-fixture",
                "capability": "usage_capture",
                "prompt": "emit fixture events",
                "expected_event_types": ["thread.started", "turn.completed"],
            }
            probe_manifest = root / "probe-host.json"
            _host_manifest(probe_manifest, fake, mode="probe")
            probe_result = _run_adapter(
                workspace,
                fake,
                probe_manifest,
                probe,
                mode="probe",
            )
            self.assertEqual(0, probe_result.returncode, probe_result.stderr)
            normalized = _jsonl(probe_result.stdout)[0]
            self.assertEqual("pass", normalized["status"])
            self.assertEqual(THREAD_ID, normalized["session_id"])
            self.assertEqual(["direct.usage"], normalized["direct_observations"])
            self.assertEqual([], normalized["routing"])

            probe["probe_id"] = "probe-multi-turn"
            probe["capability"] = "multi_turn"
            unsupported = _run_adapter(
                workspace,
                fake,
                probe_manifest,
                probe,
                mode="probe",
            )
            self.assertEqual(0, unsupported.returncode, unsupported.stderr)
            self.assertEqual("unknown", _jsonl(unsupported.stdout)[0]["status"])

            probe["capability"] = "undeclared-capability"
            rejected = _run_adapter(
                workspace,
                fake,
                probe_manifest,
                probe,
                mode="probe",
            )
            self.assertEqual(2, rejected.returncode)
            self.assertIn("interaction probe row is invalid", rejected.stderr)

    def test_process_failures_are_typed_and_stderr_is_redacted(self) -> None:
        cases = {
            "nonzero": ("failed", "codex_exit_7", 2),
            "signal": ("failed", "codex_signal_15", 2),
            "timeout": ("timeout", None, 0.05),
        }
        for mode, (status, code, timeout) in cases.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = root / "workspace"
                workspace.mkdir()
                stdout_lines = (
                    [json.dumps({
                        "type": "error",
                        "message": "Invalid response schema: prefixItems is unsupported",
                    })]
                    if mode == "nonzero"
                    else []
                )
                fake, _ = _write_fake_codex(
                    root,
                    mode=mode,
                    sleep_seconds=5,
                    stdout_lines=stdout_lines,
                )
                manifest_path = root / "host.json"
                _host_manifest(manifest_path, fake, timeout=timeout)
                started = time.monotonic()
                result = _run_adapter(
                    workspace,
                    fake,
                    manifest_path,
                    _request("execute_case", _execute_payload()),
                    timeout=timeout,
                )
                self.assertLess(time.monotonic() - started, 3)
                self.assertEqual(0, result.returncode, result.stderr)
                terminal = _jsonl(result.stdout)[-1]
                self.assertEqual(status, terminal["terminal_status"])
                self.assertEqual(code, terminal["provider_error_code"])
                if mode == "nonzero":
                    self.assertIn("prefixItems is unsupported", terminal["treatment_error"])
                self.assertEqual([], list(workspace.iterdir()))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            marker = "fixture-secret-marker-123"
            fake, _ = _write_fake_codex(
                root,
                stderr=f"secret={marker} path={workspace}",
            )
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake)
            result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", _execute_payload()),
                environment={"FRONTIER_TEST_SECRET": marker},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn(marker, result.stderr)
            self.assertNotIn(str(workspace), result.stderr)
            self.assertIn("<redacted>", result.stderr)
            self.assertIn("<workspace>", result.stderr)

    def test_bound_manifest_executable_and_request_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            fake, state = _write_fake_codex(root)
            manifest_path = root / "host.json"
            manifest = _host_manifest(manifest_path, fake)
            request = _request("execute_case", _execute_payload())

            cases: list[tuple[str, list[str], dict]] = []
            bad_manifest = json.loads(json.dumps(manifest))
            bad_manifest["identity"]["adapter"]["sha256"] = "sha256:" + "0" * 64
            bad_manifest["manifest_hash"] = canonical_hash(
                {
                    key: value
                    for key, value in bad_manifest.items()
                    if key != "manifest_hash"
                }
            )
            bad_path = root / "bad-host.json"
            bad_path.write_text(json.dumps(bad_manifest) + "\n", encoding="utf-8")
            cases.append(("adapter", _adapter_argv(fake, bad_path), request))
            stale_tool_manifest = json.loads(json.dumps(manifest))
            stale_tool_manifest["identity"]["execution"]["tool_schema_hash"] = (
                "sha256:" + "3" * 64
            )
            stale_tool_manifest["manifest_hash"] = canonical_hash(
                {
                    key: value
                    for key, value in stale_tool_manifest.items()
                    if key != "manifest_hash"
                }
            )
            stale_tool_path = root / "stale-tool-host.json"
            stale_tool_path.write_text(
                json.dumps(stale_tool_manifest) + "\n", encoding="utf-8"
            )
            stale_result = subprocess.run(
                _adapter_argv(fake, stale_tool_path),
                cwd=workspace,
                input=json.dumps(request) + "\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=4,
            )
            self.assertEqual(2, stale_result.returncode)
            self.assertIn("tool schema identity differs", stale_result.stderr)
            bad_request = json.loads(json.dumps(request))
            bad_request["request_hash"] = "sha256:" + "1" * 64
            cases.append(("request", _adapter_argv(fake, manifest_path), bad_request))
            bad_codex_hash = _adapter_argv(fake, manifest_path)
            bad_codex_hash[bad_codex_hash.index("--codex-sha256") + 1] = (
                "sha256:" + "2" * 64
            )
            cases.append(("codex", bad_codex_hash, request))
            nonfinite_timeout = _adapter_argv(fake, manifest_path)
            nonfinite_timeout[nonfinite_timeout.index("--timeout") + 1] = "inf"
            cases.append(("timeout", nonfinite_timeout, request))

            for label, argv, candidate_request in cases:
                with self.subTest(label=label):
                    result = subprocess.run(
                        argv,
                        cwd=workspace,
                        input=json.dumps(candidate_request) + "\n",
                        text=True,
                        capture_output=True,
                        check=False,
                        timeout=4,
                    )
                    self.assertEqual(2, result.returncode)
            self.assertFalse(state.exists(), "identity failures must not invoke Codex")

    def test_protocol_errors_and_unsupported_cases_fail_before_evidence_claims(
        self,
    ) -> None:
        cases = json.loads(CASES.read_text(encoding="utf-8"))["normalization_cases"]
        invalid = {
            case["id"]: case
            for case in cases
            if case["expected"]["status"] != "completed"
        }
        for case_id, case in invalid.items():
            with self.subTest(case=case_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace = root / "workspace"
                workspace.mkdir()
                records = case.get("records")
                fake, _ = _write_fake_codex(
                    root,
                    turns=[
                        {
                            "records": records,
                            "message": "fixture",
                        }
                    ],
                )
                if "raw_lines" in case:
                    Path(str(fake) + ".json").write_text(
                        json.dumps(
                            {
                                "state": str(root / "fake-codex.calls.jsonl"),
                                "thread_id": THREAD_ID,
                                "raw_lines": case["raw_lines"],
                            }
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                manifest_path = root / "host.json"
                _host_manifest(manifest_path, fake)
                result = _run_adapter(
                    workspace,
                    fake,
                    manifest_path,
                    _request("execute_case", _execute_payload()),
                )
                self.assertEqual(0, result.returncode, result.stderr)
                terminal = _jsonl(result.stdout)[-1]
                self.assertEqual("protocol_error", terminal["terminal_status"])
                self.assertIsNotNone(terminal["protocol_error"])
                self.assertEqual([], terminal["principals"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            fake, state = _write_fake_codex(root)
            manifest_path = root / "host.json"
            _host_manifest(manifest_path, fake)
            payload = _execute_payload()
            payload["execution_context"]["expected_principal_slots"] = [
                "lead",
                "reviewer",
            ]
            result = _run_adapter(
                workspace,
                fake,
                manifest_path,
                _request("execute_case", payload),
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                "protocol_error", _jsonl(result.stdout)[-1]["terminal_status"]
            )
            self.assertFalse(state.exists(), "unsupported case must not invoke Codex")


class TestCodexEvalHostIntegration(SkillEvaluatorTestCase):
    def _compile_and_run(
        self, root: Path, paths: dict[str, Path]
    ) -> tuple[dict, Path, subprocess.CompletedProcess[str]]:
        plan_path = root / "execution-plan.json"
        compile_result = self.run_cmd(
            "scripts/compile_eval_plan.py",
            str(paths["spec"]),
            str(paths["scenarios"]),
            str(paths["host"]),
            "--output",
            str(plan_path),
        )
        self.assertEqual(
            0,
            compile_result.returncode,
            compile_result.stdout + compile_result.stderr,
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        index_path = (
            root / plan["artifacts"]["root"] / plan["artifacts"]["index_relpath"]
        )
        run_result = self.run_cmd(
            "scripts/run_eval_plan.py",
            str(plan_path),
            "--index",
            str(index_path),
            "--new-attempt-budget",
            str(runner_worst_case_attempt_budget(plan)),
            timeout=20,
        )
        return plan, index_path, run_result

    def test_adapter_closes_existing_runner_and_analyzer_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake, _ = _write_fake_codex(root)
            paths = _materialize_adapter_fixture(root, fake)
            _, index_path, run_result = self._compile_and_run(root, paths)
            self.assertEqual(
                0, run_result.returncode, run_result.stdout + run_result.stderr
            )
            summary_path = root / "summary.json"
            analyze_result = self.run_cmd(
                "scripts/analyze_runs.py",
                str(index_path),
                "--spec",
                str(paths["spec"]),
                "--json",
                str(summary_path),
                "--failure-index",
                str(root / "failures.json"),
            )
            self.assertIn(
                analyze_result.returncode,
                {0, 3},
                analyze_result.stdout + analyze_result.stderr,
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual("complete", summary["evidence_status"])

    def test_protocol_error_is_an_apparatus_failure_at_runner_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake, _ = _write_fake_codex(
                root,
                turns=[
                    {
                        "records": [
                            {"type": "thread.started", "thread_id": THREAD_ID},
                            {"type": "turn.started"},
                            {"type": "future.event"},
                            {"type": "turn.completed"},
                        ]
                    }
                ],
            )
            paths = _materialize_adapter_fixture(root, fake)
            plan, index_path, run_result = self._compile_and_run(root, paths)
            self.assertEqual(
                3, run_result.returncode, run_result.stdout + run_result.stderr
            )
            self.assertFalse(index_path.exists())
            for entry in plan["entries"]:
                attempt = (
                    root
                    / plan["artifacts"]["root"]
                    / entry["artifact_relpath"]
                    / "attempt-0001"
                )
                if attempt.exists():
                    self.assertTrue((attempt / "attempt-start.json").is_file())
                    self.assertFalse((attempt / "receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
