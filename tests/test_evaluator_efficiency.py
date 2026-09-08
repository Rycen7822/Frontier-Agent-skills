"""Offline acceptance of the compact evaluator's execution and reuse boundaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill-evaluator/scripts"))
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_runs
import evaluate
import evidence_io
import execution
import grading
import task_results
import usage_costs


class ChangePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        (self.root / "README.md").write_text("Documentation\n")
        (self.root / "demo").mkdir()
        (self.root / "demo/SKILL.md").write_text("Check the result.\n")
        (self.root / "bundle-manifest.json").write_text(
            json.dumps({"bundle_version": "1", "remote_writes": False})
        )
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        )
        self.marker = Path(self.temp.name) / "provider-called"
        bin_dir = Path(self.temp.name) / "bin"
        bin_dir.mkdir()
        for name in ("codex", "hermes"):
            stub = bin_dir / name
            stub.write_text(f"#!/bin/sh\ntouch '{self.marker}'\nexit 99\n")
            stub.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True
        )

    def check(self, impact="auto", base="HEAD"):
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "skill-evaluator/scripts/evaluate.py"),
                "check",
                "--root",
                str(self.root),
                "--base",
                base,
                "--impact",
                impact,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        result = json.loads(process.stdout)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / ".work").exists())
        self.assertEqual(0, result["model_calls"])
        return process.returncode, result

    def test_no_change_and_unrelated_document_need_no_provider_or_history(self):
        self.assertEqual("skip", self.check()[1]["action"])
        (self.root / "README.md").write_text("Corrected documentation\n")
        code, result = self.check()
        self.assertEqual(0, code)
        self.assertEqual("skip", result["action"])

    def test_editorial_visible_change_carries_forward_without_history(self):
        (self.root / "demo/SKILL.md").write_text("Verify the result.\n")
        code, result = self.check("editorial")
        self.assertEqual(0, code)
        self.assertEqual("carry_forward", result["action"])
        self.assertFalse(result["new_behavior_evidence"])

    def test_changed_command_is_not_automatically_exempt(self):
        (self.root / "demo/SKILL.md").write_text("Run tool --delete.\n")
        code, result = self.check()
        self.assertEqual(2, code)
        self.assertEqual("needs_scoped_evidence", result["action"])
        self.assertEqual(["demo/SKILL.md"], result["affected_paths"])

    def test_version_change_is_exempt_but_permission_change_is_not(self):
        path = self.root / "bundle-manifest.json"
        path.write_text(json.dumps({"bundle_version": "2", "remote_writes": False}))
        self.assertEqual(0, self.check()[0])
        path.write_text(json.dumps({"bundle_version": "2", "remote_writes": True}))
        self.assertEqual(2, self.check()[0])

    def test_generated_hash_does_not_invalidate_skill_evidence(self):
        (self.root / "frontier-engineering.bundle.json").write_text(
            '{"root_hash":"new"}'
        )
        self.assertEqual("skip", self.check()[1]["action"])

    def test_editorial_declaration_does_not_hide_invalid_local_code(self):
        (self.root / "demo/broken.py").write_text("def broken(:\n")
        code, result = self.check("editorial")
        self.assertEqual(1, code)
        self.assertEqual("local_check_failed", result["action"])

    def test_missing_baseline_does_not_start_a_campaign(self):
        code, result = self.check(base="missing-revision")
        self.assertEqual(2, code)
        self.assertEqual("baseline_unavailable", result["reason"])


class RuntimePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = self.root / "calls.jsonl"
        binary = self.root / "codex"
        binary.write_text(
            f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
            f"with Path({str(self.calls)!r}).open('a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')\n"
            "if '--version' in sys.argv: print('fixture-cli 1'); sys.exit(0)\n"
            "if any(x.startswith('default_permissions=') for x in sys.argv): print('unexpected argument -P', file=sys.stderr); sys.exit(2)\n"
            "if '--help' not in sys.argv: print('MODEL EXECUTION FORBIDDEN', file=sys.stderr); sys.exit(99)\n"
            "print('fixture help')\n"
        )
        binary.chmod(0o755)
        self.args = SimpleNamespace(
            codex=binary,
            sandbox="read-only",
            isolation_tool=None,
            model="fixture-model",
            effort="medium",
            profile="none",
            runtime_surface_version=None,
            plugin_root=None,
        )
        evaluate._PREFLIGHT_CACHE.clear()

    def test_parser_rejection_precedes_any_execution_or_materialization(self):
        self.args.isolation_tool = Path("/fixture/bwrap")
        with self.assertRaisesRegex(ValueError, "unexpected argument -P"):
            evaluate.preflight_runtime(self.args, self.root)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(2, len(calls))
        self.assertTrue(all("--version" in c or "--help" in c for c in calls))
        self.assertFalse((self.root / "preflight-last-message").exists())

    def test_fresh_resume_are_checked_and_unchanged_parser_evidence_is_reused(self):
        first = evaluate.preflight_runtime(self.args, self.root)
        second = evaluate.preflight_runtime(self.args, self.root)
        self.assertEqual(["fresh", "resume"], first["checks"])
        self.assertTrue(second["reused"])
        self.assertEqual("pending_execution", first["runtime_validation"])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(2, sum("--help" in c for c in calls))
        self.args.effort = "high"
        self.assertFalse(evaluate.preflight_runtime(self.args, self.root)["reused"])


class CoreFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        fixture = ROOT / "evaluation/fixtures/skill-evaluator"
        for name in ("synthetic-host.py", "synthetic-model-host.py"):
            shutil.copy2(fixture / name, self.source / name)
        self.suite = json.loads((fixture / "author-suite.json").read_text())
        self.host = json.loads((fixture / "host-manifest-v2.json").read_text())
        executable = Path(sys.executable).resolve()
        self.host["command"].update(
            argv=[str(executable), "synthetic-host.py"],
            resolved_executable=str(executable),
            executable_digest=evidence_io.file_sha256(executable),
        )
        self.suite["graders"][0]["verifier"]["argv"][0] = str(executable)
        self.number = 0
        self.save()

    def save(self):
        (self.source / "suite.json").write_text(json.dumps(self.suite))
        (self.source / "host.json").write_text(json.dumps(self.host))

    def run_suite(self, **changes):
        self.number += 1
        args = SimpleNamespace(
            suite=self.source / "suite.json",
            host=self.source / "host.json",
            output=self.root / str(self.number),
            previous_report=None,
            case=None,
            max_parallel=2,
            task_attempt_budget=4,
            judge_invocation_budget=0,
            impact="auto",
        )
        for name, value in changes.items():
            setattr(args, name, value)
        return evaluate.run_suite(args), args.output

    def models(self):
        self.host["schema_version"] = 3
        self.host["command"]["argv"][1:] = [
            "synthetic-model-host.py",
            "--roles",
            "synthetic-host.py",
        ]
        self.host["identity"]["grading"] = {
            **self.host["identity"]["execution"],
            "model": "fixture-judge",
            "pricing_id": "judge-price",
        }
        self.suite["graders"].append(
            {
                "grader_id": "model-grader",
                "type": "model",
                "prompt": "Judge every check from the captured evidence.",
                "checks": [
                    {
                        "check_id": "quality-check",
                        "dimension": "quality",
                        "required": True,
                        "pass_condition": "The answer is complete.",
                    }
                ],
            }
        )
        for case in self.suite["cases"]:
            case["requirements"].append(
                {"grader_id": "model-grader", "check_id": "quality-check"}
            )
        self.save()

    def test_selected_case_runs_real_oracle_without_formal_files(self):
        result, output = self.run_suite(case=["case-basic"])
        self.assertEqual((result["task_attempts"], result["judge_invocations"]), (2, 0))
        self.assertEqual(result["evidence_status"], "complete")
        self.assertEqual(result["usefulness_status"], "diagnostic_only")
        self.assertEqual(result["failures"], [])
        self.assertEqual(len(list((output / "tasks").glob("*/task.json"))), 2)
        self.assertFalse((output / "plan.json").exists())
        self.assertFalse((output / "spec.json").exists())
        self.assertNotIn("case-secondary", (output / "run.json").read_text())

    def test_exact_reuse_does_no_preflight_execution_grading_or_preparation(self):
        _, before = self.run_suite()
        with (
            mock.patch.object(
                evaluate, "_host_preflight", side_effect=AssertionError("preflight")
            ),
            mock.patch.object(
                execution, "execute_task", side_effect=AssertionError("task")
            ),
            mock.patch.object(
                grading, "deterministic", side_effect=AssertionError("grader")
            ),
        ):
            result, output = self.run_suite(
                previous_report=before / "summary.json", task_attempt_budget=0
            )
        self.assertEqual(result["action"], "reuse_exact")
        self.assertEqual(result["costs"]["task"]["input_tokens"], 0)
        self.assertEqual(result["costs"]["judge"]["input_tokens"], 0)
        self.assertEqual(
            {p.name for p in output.iterdir()}, {".run.lock", "summary.json"}
        )

    def test_missing_budget_precedes_preflight_and_output(self):
        with mock.patch.object(
            evaluate, "_host_preflight", side_effect=AssertionError("preflight")
        ):
            result, output = self.run_suite(task_attempt_budget=3)
        self.assertEqual(result["required_task_attempts"], 4)
        self.assertEqual(result["task_attempts"], 0)
        self.assertFalse(output.exists())

    def test_skill_change_reuses_baselines_and_compares_previous_candidates(self):
        _, before = self.run_suite()
        self.host["catalog"]["entries"][0]["root_digest"] = "sha256:" + "a" * 64
        self.save()
        result, output = self.run_suite(
            previous_report=before / "summary.json", task_attempt_budget=2
        )
        self.assertEqual(result["task_attempts"], 2)
        self.assertEqual(result["comparisons"]["previous"]["case_count"], 2)
        summary = json.loads((output / "summary.json").read_text())
        baselines = [r for r in summary["records"] if r["position"][1] == "baseline"]
        self.assertTrue(all(str(before) in r["source"]["path"] for r in baselines))

    def test_deterministic_rule_change_reuses_all_tasks(self):
        _, before = self.run_suite()
        self.suite["graders"][0]["checks"][0]["pass_condition"] += (
            " with the updated rule"
        )
        self.save()
        with mock.patch.object(
            execution, "execute_task", side_effect=AssertionError("task")
        ):
            result, output = self.run_suite(
                previous_report=before / "summary.json", task_attempt_budget=0
            )
        self.assertEqual(result["action"], "regrade")
        self.assertEqual((result["task_attempts"], result["judge_invocations"]), (0, 0))
        self.assertFalse((output / "tasks").exists())

    def test_judge_failure_continues_only_the_missing_batch(self):
        self.models()
        _, before = self.run_suite(judge_invocation_budget=2)
        self.suite["graders"][-1]["prompt"] += " Updated rubric."
        self.save()
        invoke = grading.invoke
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("interrupted judge")
            return invoke(*args, **kwargs)

        with mock.patch.object(grading, "invoke", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "interrupted judge"):
                self.run_suite(
                    previous_report=before / "summary.json",
                    task_attempt_budget=0,
                    judge_invocation_budget=2,
                )
        failed = self.root / str(self.number)
        report = json.loads((failed / "summary.json").read_text())
        self.assertIsNone(report["costs"]["judge"]["input_tokens"])
        result, _ = self.run_suite(
            previous_report=failed / "summary.json",
            task_attempt_budget=0,
            judge_invocation_budget=1,
        )
        self.assertEqual((result["task_attempts"], result["judge_invocations"]), (0, 1))
        self.assertEqual(result["evidence_status"], "complete")

    def test_completed_task_is_recovered_when_report_commit_fails(self):
        original = evidence_io.atomic_write_json

        def fail_report(path, value, **kwargs):
            if path.name == "summary.json" and value.get("records"):
                raise OSError("report commit interrupted")
            return original(path, value, **kwargs)

        with mock.patch.object(
            evidence_io, "atomic_write_json", side_effect=fail_report
        ):
            with self.assertRaisesRegex(OSError, "report commit interrupted"):
                self.run_suite()
        failed = self.root / str(self.number)
        completed = len(list((failed / "tasks").glob("*/task.json")))
        self.assertGreater(completed, 0)
        result, _ = self.run_suite(
            previous_report=failed / "summary.json", task_attempt_budget=4 - completed
        )
        self.assertEqual(result["task_attempts"], 4 - completed)
        self.assertEqual(result["evidence_status"], "complete")

    def test_selected_tampered_task_is_rejected_before_output(self):
        _, before = self.run_suite()
        summary = json.loads((before / "summary.json").read_text())
        Path(summary["records"][0]["source"]["path"]).write_text("{}")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.run_suite(
                previous_report=before / "summary.json", task_attempt_budget=0
            )
        self.assertFalse((self.root / str(self.number)).exists())

    def test_fixture_model_and_effort_changes_need_selected_tasks(self):
        _, before = self.run_suite()
        original_host = copy.deepcopy(self.host)
        for field in ("model", "effort"):
            with self.subTest(field=field):
                self.host = copy.deepcopy(original_host)
                self.host["identity"]["execution"][field] = "changed"
                self.save()
                result, output = self.run_suite(
                    previous_report=before / "summary.json", task_attempt_budget=0
                )
                self.assertEqual(result["required_task_attempts"], 4)
                self.assertFalse(output.exists())
        self.host = original_host
        (self.source / "input.txt").write_text("new fixture")
        self.suite["cases"][0]["fixture"] = {"initial_files": [{"path": "input.txt"}]}
        self.save()
        result, _ = self.run_suite(
            previous_report=before / "summary.json", task_attempt_budget=0
        )
        self.assertEqual(result["required_task_attempts"], 2)

    def test_price_version_metadata_does_not_force_tasks(self):
        _, before = self.run_suite()
        self.host["identity"]["execution"]["pricing_id"] = "new-price"
        self.host["identity"]["repository"]["revision"] = "b" * 40
        self.host["catalog"]["entries"][0]["version"] = "99.0.0"
        self.save()
        result, _ = self.run_suite(
            previous_report=before / "summary.json", task_attempt_budget=0
        )
        self.assertEqual(result["action"], "reuse_exact")

    def test_judge_identity_changes_only_grading_dependencies(self):
        self.models()
        _, before = self.run_suite(judge_invocation_budget=2)
        self.host["identity"]["grading"]["model"] = "different-judge"
        self.save()
        result, output = self.run_suite(
            previous_report=before / "summary.json", task_attempt_budget=0
        )
        self.assertEqual(result["required_task_attempts"], 0)
        self.assertEqual(result["required_judge_invocations"], 2)
        self.assertFalse(output.exists())

    def test_missing_usage_and_unknown_principals_are_not_zero_success(self):
        _, before = self.run_suite(case=["case-basic"])
        view = json.loads((before / "summary.json").read_text())["records"][0]
        record = task_results.read_task(view["source"])
        result = copy.deepcopy(record["result"])
        result["usage"]["records"] = []
        cost = usage_costs.captured_usage(
            result, record["task"]["entry"], self.host, role="task"
        )
        self.assertIsNone(cost["input_tokens"])
        result = copy.deepcopy(record["result"])
        result["usage"]["records"][0]["principal_id"] = "unbound"
        with self.assertRaisesRegex(ValueError, "unbound"):
            usage_costs.captured_usage(
                result, record["task"]["entry"], self.host, role="task"
            )

    def test_completed_failed_checks_remain_outcome_failures(self):
        verifier = self.source / "synthetic-host.py"
        verifier.write_text(
            verifier.read_text().replace('"pass": True,', '"pass": False,')
        )
        result, _ = self.run_suite(case=["case-basic"])
        self.assertEqual(result["evidence_status"], "complete")
        self.assertEqual(len(result["failures"]), 2)
        self.assertTrue(all(not row["task_pass"] for row in result["failures"]))


class ExecutionBoundaryTests(unittest.TestCase):
    def entry(self, case, repeat=1, resources=()):
        return {"case_id": case, "repeat": repeat, "shared_resources": list(resources)}

    def test_case_lanes_overlap_but_each_case_stays_ordered(self):
        gate = threading.Barrier(2)
        seen = []
        lock = threading.Lock()

        def worker(entry):
            if entry["repeat"] == 1:
                gate.wait(timeout=2)
            with lock:
                seen.append((entry["case_id"], entry["repeat"]))
            return entry

        execution.run_tasks(
            [self.entry(c, r) for c in ("a", "b") for r in (1, 2)],
            max_parallel=2,
            worker=worker,
            on_complete=lambda _: None,
        )
        for case in ("a", "b"):
            self.assertEqual([r for c, r in seen if c == case], [1, 2])

    def test_shared_resources_are_serialized(self):
        active = 0
        maximum = 0

        def worker(entry):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            time.sleep(0.02)
            active -= 1
            return entry

        execution.run_tasks(
            [self.entry(c, resources=["shared"]) for c in ("a", "b")],
            max_parallel=2,
            worker=worker,
            on_complete=lambda _: None,
        )
        self.assertEqual(maximum, 1)

    def test_concurrent_reservations_cannot_overspend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = execution.Budget(1, 0, root)

            def reserve(i):
                try:
                    budget.reserve("task", str(i))
                    return True
                except ValueError:
                    return False

            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(reserve, range(8))), 1)
            value = json.loads((root / "attempts.json").read_text())
            self.assertEqual(value["used"]["task"], 1)
            self.assertEqual(len(value["attempts"]), 1)

    def test_live_child_keeps_custody_after_parent_closes_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with execution.RunLock(root) as lock:
                child = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(0.3)"],
                    pass_fds=(lock.fd,),
                )
            try:
                with self.assertRaises(BlockingIOError):
                    with execution.RunLock(root):
                        pass
            finally:
                child.wait(timeout=3)
            with execution.RunLock(root):
                pass

    def test_intervals_count_cases_not_repeats_and_missing_pairs_stay_incomplete(self):
        rows = [
            {
                "case_id": "a",
                "repeat": i,
                "variant": variant,
                "task_pass": variant == "candidate",
                "evidence_complete": True,
            }
            for i in range(1, 8)
            for variant in ("baseline", "candidate")
        ]
        result = analyze_runs.paired_comparison(rows, comparator="baseline")
        self.assertEqual(result["case_count"], 1)
        self.assertIsNone(result["lower"])
        rows.pop()
        self.assertEqual(
            analyze_runs.paired_comparison(rows, comparator="baseline")["status"],
            "not_evaluable",
        )


if __name__ == "__main__":
    unittest.main()
