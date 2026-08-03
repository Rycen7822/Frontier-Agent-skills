from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from skill_evaluator_test_support import (
    SkillEvaluatorTestCase,
    canonical_hash,
    materialize_v5_contract_fixture,
    rebind_v5_contract_fixture,
    runner_worst_case_attempt_budget,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
        handle.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt}) + "\\n")

    stderr = config.get("stderr")
    if stderr:
        sys.stderr.write(stderr)
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
        "--host-manifest",
        str(manifest),
        "--model",
        MODEL,
        "--effort",
        "high",
        "--profile",
        "fixture-profile",
        "--sandbox",
        "workspace-write",
        "--timeout",
        str(timeout),
    ]


def _host_manifest(
    path: Path,
    fake: Path,
    *,
    mode: str = "host",
    timeout: float = 2,
) -> dict:
    manifest = json.loads(
        (
            REPOSITORY_ROOT / "tests/fixtures/skill_evaluator/host-manifest-v1.json"
        ).read_text(encoding="utf-8")
    )
    manifest["identity"]["adapter"].update(
        {
            "id": "codex-eval-host",
            "version": "1",
            "sha256": _sha256_file(ADAPTER),
        }
    )
    manifest["identity"]["execution"]["model"] = MODEL
    manifest["command"].update(
        {
            "argv": _bound_adapter_argv(fake, path, mode=mode, timeout=timeout),
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
            "version": "1",
            "sha256": _sha256_file(ADAPTER),
        }
    )
    host["identity"]["execution"]["model"] = MODEL
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
            "request_kind": kind,
            "request_id": f"request-{kind}",
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
    fake: Path, manifest: Path, *, mode: str = "host", timeout: float = 2
) -> list[str]:
    return _bound_adapter_argv(fake, manifest, mode=mode, timeout=timeout)


def _run_adapter(
    workspace: Path,
    fake: Path,
    manifest: Path,
    request: dict,
    *,
    mode: str = "host",
    timeout: float = 2,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    child_environment = dict(os.environ)
    child_environment.update(environment or {})
    return subprocess.run(
        _adapter_argv(fake, manifest, mode=mode, timeout=timeout),
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

    def test_model_grade_schema_binds_batch_and_check_order(self) -> None:
        batch = {
            "batch_id": "batch-1",
            "items": [
                {
                    "item_id": "item-1",
                    "checks": [{"id": "check-a"}, {"id": "check-b"}],
                }
            ],
        }
        schema = self.events.model_grade_schema(batch)
        self.assertEqual("batch-1", schema["properties"]["batch_id"]["const"])
        item = schema["properties"]["items"]["prefixItems"][0]
        self.assertEqual("item-1", item["properties"]["item_id"]["const"])
        self.assertEqual(
            ["check-a", "check-b"],
            [
                entry["properties"]["id"]["const"]
                for entry in item["properties"]["checks"]["prefixItems"]
            ],
        )


class TestCodexEvalHostProcess(SkillEvaluatorTestCase):
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
            self.assertEqual(THREAD_ID, records[-1]["principals"][0]["session_id"])
            self.assertEqual(
                10, records[0]["payload"]["codex"]["usage"]["input_tokens"]
            )
            self.assertEqual("missing", records[-1]["context"]["status"])
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
            artifacts = records[-1]["artifacts"]
            self.assertEqual(1, len(artifacts))
            self.assertTrue((workspace / Path(artifacts[0]["path"]).name).is_file())
            self.assertEqual(
                [Path(artifacts[0]["path"]).name],
                sorted(path.name for path in workspace.iterdir()),
            )

    def test_model_grade_and_probe_use_closed_outputs(self) -> None:
        grade = {
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
            fake, state = _write_fake_codex(root, grade=grade)
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
                _request("model_grade", {"blinded_input": batch}),
            )
            self.assertEqual(0, grade_result.returncode, grade_result.stderr)
            grade_record = _jsonl(grade_result.stdout)[-1]
            self.assertEqual("completed", grade_record["terminal_status"])
            self.assertEqual(1, len(grade_record["artifacts"]))
            artifact = workspace / Path(grade_record["artifacts"][0]["path"]).name
            self.assertEqual(grade, json.loads(artifact.read_text(encoding="utf-8")))
            grade_call = _jsonl(state.read_text(encoding="utf-8"))[0]
            self.assertIn("--output-schema", grade_call["argv"])
            self.assertNotIn("treatment", grade_call["prompt"].lower())

            probe = {
                "schema_version": "codex-interaction-probe/1.0",
                "probe_id": "probe-fixture",
                "capability": "session-events",
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
                fake, _ = _write_fake_codex(root, mode=mode, sleep_seconds=5)
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
                2, run_result.returncode, run_result.stdout + run_result.stderr
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
