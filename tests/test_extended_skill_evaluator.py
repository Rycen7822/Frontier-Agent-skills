from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill-evaluator"
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
READY_FIXTURES = (
    "grader-output.schema.json",
    "host-manifest-v2.json",
    "scenarios-v1.jsonl",
    "spec-v7.json",
    "suite-quality-proof.json",
    "suite-quality-v2.json",
    "synthetic-host.py",
)


def run_script(relative: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative), *arguments],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


class ExtendedSkillEvaluator(unittest.TestCase):
    def test_qualification_axes_are_non_compensating(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from _model_evolution_qualification import GATE_IDS, derive_decision

        for failed_gate in ("operational_cost", "loop_pathology"):
            gates = [
                {"status": "blocked" if gate_id == failed_gate else "pass"}
                for gate_id in GATE_IDS
            ]
            self.assertEqual("blocked", derive_decision(gates, [], []))

    def test_host_artifacts_are_fixed_bounded_and_replayable(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from _codex_eval_artifacts import (
            WorkspaceEvidence,
            build_command_trace,
        )
        from _codex_eval_delivery import is_workspace_infrastructure

        captures = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                target = workspace / "src.txt"
                target.write_bytes(b"before\r\n")
                timeline = WorkspaceEvidence(
                    workspace,
                    ignored=is_workspace_infrastructure,
                )
                timeline.capture_initial()
                target.write_bytes(b"after\n")
                timeline.capture_turn("turn-1")
                turn = {
                    "items": [
                        {
                            "phase": "completed",
                            "type": "command_execution",
                            "status": "completed",
                            "exit_code": 0,
                            "command": f"python {target}\r\n",
                            "aggregated_output": f"updated {target}\r\n",
                        },
                        {
                            "phase": "completed",
                            "type": "file_change",
                            "changes": [{"path": str(target), "kind": "update"}],
                        },
                    ]
                }
                trace = build_command_trace(
                    [turn],
                    ["turn-1"],
                    workspace=workspace,
                    workspace_alias="/tmp/frontier-workspace",
                    normalize_text=lambda value: value.replace(
                        str(workspace), "<workspace>"
                    ),
                )
                evidence, changed = timeline.finish()
                captures.append((trace, evidence, changed))

        self.assertEqual(captures[0], captures[1])
        trace, evidence, changed = captures[0]
        self.assertTrue(trace["complete"])
        self.assertFalse(trace["overflow"])
        self.assertEqual(
            "python <workspace>/src.txt\n",
            trace["items"][0]["command_preview"],
        )
        self.assertEqual(
            [{"path": "src.txt", "action": "modify"}],
            trace["items"][1]["changes"],
        )
        self.assertEqual(["src.txt"], changed)
        self.assertTrue(evidence["complete"])
        self.assertIn("--- a/src.txt", evidence["diff"])

        escaped = build_command_trace(
            [{"items": [{
                "phase": "completed",
                "type": "file_change",
                "changes": [{"path": "/outside.txt", "kind": "update"}],
            }]}],
            ["turn-1"],
            workspace=ROOT,
            workspace_alias="/tmp/frontier-workspace",
            normalize_text=lambda value: value,
        )
        self.assertFalse(escaped["complete"])

        command = {
            "phase": "completed",
            "type": "command_execution",
            "status": "failed",
            "exit_code": 1,
            "command": "false",
            "aggregated_output": "failed",
        }
        overflow = build_command_trace(
            [{"items": [dict(command) for _ in range(257)]}],
            ["turn-1"],
            workspace=ROOT,
            workspace_alias="/tmp/frontier-workspace",
            normalize_text=lambda value: value,
        )
        self.assertEqual(256, len(overflow["items"]))
        self.assertTrue(overflow["overflow"])
        self.assertFalse(overflow["complete"])

    def test_invalid_contract_is_rejected(self) -> None:
        base = json.loads(
            (SKILL / "templates" / "eval-spec.example.json").read_text(encoding="utf-8")
        )
        for label, mutate, expected in (
            ("extra-field", lambda spec: spec.__setitem__("unexpected", True), "schema.additionalProperties"),
            ("missing-axis", lambda spec: spec["hard_gates"][0].pop("decision_axis"), "schema.required"),
            ("old-epoch", lambda spec: spec.__setitem__("schema_version", 6), "schema.const"),
            (
                "undeclared-grader-input",
                lambda spec: spec["graders"][0]["verifier"]["input_allowlist"].append("workspace/other.json"),
                "schema.oneOf",
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                spec = json.loads(json.dumps(base))
                mutate(spec)
                spec_path = Path(directory) / "spec.json"
                spec_path.write_text(json.dumps(spec), encoding="utf-8")
                result = run_script(
                    "skill-evaluator/scripts/validate_eval_suite.py", "contract",
                    str(spec_path), str(SKILL / "templates" / "scenarios.example.jsonl"),
                    str(SKILL / "templates" / "host-manifest.example.json"), "--json", "-",
                )
                self.assertEqual(1, result.returncode)
                self.assertIn(expected, {error["code"] for error in json.loads(result.stdout)["errors"]})

    def test_compile_run_and_analyze_public_lifecycle(self) -> None:
        fixture_root = ROOT / "evaluation" / "fixtures" / "skill-evaluator"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in READY_FIXTURES:
                shutil.copy2(fixture_root / name, work / name)

            plan = work / "plan.json"
            compiled = run_script(
                "skill-evaluator/scripts/compile_eval_plan.py",
                str(work / "spec-v7.json"),
                str(work / "scenarios-v1.jsonl"),
                str(work / "host-manifest-v2.json"),
                "--output",
                str(plan),
            )
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            plan_value = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual(3, plan_value["schema_version"])
            self.assertEqual(
                {"execute": 2, "not_evaluable": 0, "total": 2, "unsupported": 0},
                plan_value["expected_counts"],
            )
            old_plan = work / "old-plan.json"
            old_plan_value = {**plan_value, "schema_version": 2}
            old_plan.write_text(json.dumps(old_plan_value), encoding="utf-8")
            rejected_plan = run_script(
                "skill-evaluator/scripts/run_eval_plan.py",
                str(old_plan),
                "--index",
                str(work / "old-index.jsonl"),
                "--status",
            )
            self.assertNotEqual(0, rejected_plan.returncode)
            self.assertIn(
                "schema",
                (rejected_plan.stdout + rejected_plan.stderr).lower(),
            )

            index = work / "artifacts" / "index.jsonl"
            executed = run_script(
                "skill-evaluator/scripts/run_eval_plan.py",
                str(plan),
                "--index",
                str(index),
                "--new-attempt-budget",
                "2",
            )
            self.assertEqual(0, executed.returncode, executed.stdout + executed.stderr)
            status = run_script(
                "skill-evaluator/scripts/run_eval_plan.py",
                str(plan),
                "--index",
                str(index),
                "--status",
            )
            self.assertEqual(0, status.returncode, status.stdout + status.stderr)
            self.assertEqual(
                (2, 2, 0, []),
                tuple(
                    json.loads(status.stdout)[key]
                    for key in (
                        "completed_entries",
                        "indexed_attempts",
                        "remaining_entries",
                        "active_attempts",
                    )
                ),
            )

            summary = work / "summary.json"
            failures = work / "failures.json"
            analyzed = run_script(
                "skill-evaluator/scripts/analyze_runs.py",
                str(index),
                "--spec",
                str(work / "spec-v7.json"),
                "--json",
                str(summary),
                "--failure-index",
                str(failures),
            )
            self.assertEqual(3, analyzed.returncode, analyzed.stdout + analyzed.stderr)
            summary_value = json.loads(summary.read_text())
            self.assertEqual(6, summary_value["schema_version"])
            self.assertEqual("complete", summary_value["evidence_status"])
            self.assertEqual("inconclusive_ceiling", summary_value["usefulness_status"])
            self.assertTrue(summary_value["baseline_ceiling"])
            self.assertEqual(
                [("task-gate", "task_behavior", "not_evaluable")],
                [
                    (item["gate_id"], item["decision_axis"], item["status"])
                    for item in summary_value["gate_results"]
                ],
            )
            sys.path.insert(0, str(ROOT / "scripts"))
            from _model_evolution_contract import ContractError, evaluator_summary_axes

            expected_gates = json.loads((work / "spec-v7.json").read_text())["hard_gates"]
            for label, field, value in (
                ("forged-status", "status", "pass"),
                ("cross-axis-alias", "decision_axis", "operational_cost"),
                ("old-summary", "schema_version", 5),
            ):
                forged = json.loads(json.dumps(summary_value))
                if field == "schema_version":
                    forged[field] = value
                else:
                    forged["gate_results"][0][field] = value
                forged_path = work / f"{label}.json"
                forged_path.write_text(json.dumps(forged), encoding="utf-8")
                with self.subTest(label=label), self.assertRaises(ContractError):
                    evaluator_summary_axes(
                        forged_path,
                        kind="current_summary",
                        expected_gates=expected_gates,
                    )
            mixed = json.loads(json.dumps(summary_value))
            failed_result = {**mixed["gate_results"][0]}
            failed_result.update(
                gate_id="task-failure", observed=-1.0, status="fail"
            )
            mixed["gate_results"].append(failed_result)
            mixed_path = work / "mixed-gates.json"
            mixed_path.write_text(json.dumps(mixed), encoding="utf-8")
            failed_gate = {**expected_gates[0], "gate_id": "task-failure"}
            self.assertEqual(
                "blocked",
                evaluator_summary_axes(
                    mixed_path,
                    kind="current_summary",
                    expected_gates=[*expected_gates, failed_gate],
                )["task_behavior"],
            )
            self.assertEqual(2, len(list(work.glob("artifacts/entries/*/attempt-0001/receipt.json"))))
            self.assertEqual([], list(work.glob("artifacts/entries/*/attempt-0002")))

    def test_package_auditor_checks_real_skills_and_broken_input(self) -> None:
        for skill_id in (
            "long-document-segmented-writing",
            "skill-evaluator",
            "software-quality-workflows",
            "writing-plans",
        ):
            with self.subTest(skill=skill_id):
                result = run_script(
                    "skill-evaluator/scripts/audit_skill_package.py",
                    str(ROOT / skill_id),
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "SKILL.md").write_text(
                "---\nname: broken\ndescription: Broken fixture.\n---\n\n"
                "[missing](references/missing.md)\n",
                encoding="utf-8",
            )
            rejected = run_script(
                "skill-evaluator/scripts/audit_skill_package.py",
                str(package),
            )
        self.assertEqual(1, rejected.returncode)
        self.assertIn("broken local Markdown link", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
