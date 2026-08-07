from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "skill-evaluator/scripts"))

import _model_evolution_sentinel_builder as sentinel_builder  # noqa: E402
import analyze_runs  # noqa: E402
import grader_semantics  # noqa: E402
import run_eval_plan  # noqa: E402
from _model_evolution_contract import (  # noqa: E402
    SKILL_IDS,
    load_json,
    resolve_binding,
    validate_document,
)
from _model_evolution_qualification import (  # noqa: E402
    CRITICAL_PROBE_CAPABILITIES,
)

MODEL_ROOT = REPOSITORY_ROOT / "evaluation/model-evolution"
SENTINEL_ROOT = MODEL_ROOT / "sentinels"


class ModelEvolutionSentinelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = load_json(
            MODEL_ROOT / "sentinel-index-v1.json", label="sentinel index"
        )
        cls.probes = load_json(
            MODEL_ROOT / "codex-interaction-probes-v1.json", label="probe set"
        )

    def test_generator_check_is_deterministic(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts/build_model_evolution_sentinels.py"),
                "--check",
            ],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True})

    def test_index_is_exact_four_and_every_binding_resolves(self) -> None:
        validate_document(self.index, "sentinel_index")
        self.assertEqual(set(self.index["skills"]), set(SKILL_IDS))
        for record in self.index["skills"].values():
            bindings = [
                record["spec_template"],
                record["public_scenarios"],
                *record["fixture_roots"],
                *record["verifier_roots"],
            ]
            for binding in bindings:
                resolved = resolve_binding(
                    binding,
                    REPOSITORY_ROOT,
                    REPOSITORY_ROOT / ".work/unused-campaign-root",
                )
                self.assertTrue(resolved.is_file())

    def test_public_scenarios_close_coverage_and_protected_contracts(self) -> None:
        for skill_id, record in self.index["skills"].items():
            path = resolve_binding(
                record["public_scenarios"],
                REPOSITORY_ROOT,
                REPOSITORY_ROOT / ".work/unused-campaign-root",
            )
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 6)
            self.assertEqual(len({row["case_id"] for row in rows}), 6)
            forbidden_placeholders = (
                "for the stated claim",
                "the routine local change",
                "the requested technical report",
                "the ordinary task",
            )
            for row in rows:
                task = row["execution_context"]["task"]
                self.assertEqual(task, row["turns"][0]["input"]["content"])
                self.assertTrue(task.strip())
                self.assertFalse(
                    any(phrase in task.lower() for phrase in forbidden_placeholders),
                    f"{row['case_id']} retains an unspecified placeholder task",
                )
                self.assertEqual(
                    600 * len(row["turns"]) + 30,
                    row["timeout_seconds"],
                )
            spec = load_json(
                SENTINEL_ROOT / skill_id / "eval-spec.template.json",
                label="sentinel spec",
            )
            self.assertEqual(1230, spec["execution"]["timeout_seconds"])
            tags = {tag for row in rows for tag in row["tags"]}
            self.assertLessEqual(set(record["required_coverage_tags"]), tags)
            by_id = {row["case_id"]: row for row in rows}
            definition_config = sentinel_builder.SKILLS[skill_id]
            manifest = load_json(
                SENTINEL_ROOT / skill_id / "fixtures/manifest.json",
                label="fixture manifest",
            )
            self.assertEqual(
                {f"fixtures/{artifact['path']}" for artifact in manifest["artifacts"]},
                set(definition_config["fixtures"]),
            )
            definitions = {
                f"{skill_id}-{case['id']}": case for case in definition_config["cases"]
            }
            self.assertEqual(set(by_id), set(definitions))
            for case_id, row in by_id.items():
                definition = definitions[case_id]
                initial_files = row["fixture"]["initial_files"]
                self.assertEqual(
                    [item["path"] for item in initial_files],
                    definition["initial_files"],
                )
                self.assertTrue(definition["semantic_oracle"])
                for expected_fact in definition["semantic_oracle"]:
                    self.assertNotIn(
                        expected_fact.casefold(),
                        row["execution_context"]["task"].casefold(),
                    )
                for item in initial_files:
                    fixture = SENTINEL_ROOT / skill_id / item["path"]
                    self.assertTrue(fixture.is_file(), fixture)
                    self.assertEqual(
                        item["sha256"],
                        "sha256:" + hashlib.sha256(fixture.read_bytes()).hexdigest(),
                    )
                    self.assertIn(item["path"], row["execution_context"]["task"])
            self.assertNotIn(
                "fixtures/task.json",
                {
                    item["path"]
                    for row in rows
                    for item in row["fixture"]["initial_files"]
                },
            )
            for protected_id in record["protected_case_ids"]:
                protected = by_id[protected_id]
                self.assertFalse(protected["attribution_evaluable"])
                self.assertEqual(
                    set(protected["applicable_treatment_profiles"]),
                    {"baseline/skill_disabled", "candidate/force_loaded"},
                )
                self.assertIn(
                    "outcome",
                    {
                        requirement["dimension"]
                        for requirement in protected["requirements"]
                        if requirement["required"]
                    },
                )
            self.assertTrue(
                any(len(row["turns"]) == 2 for row in rows),
                f"{skill_id} lacks an exact-session continuation case",
            )

    def test_nonready_specs_pass_existing_contract_with_only_expected_warnings(
        self,
    ) -> None:
        for skill_id in SKILL_IDS:
            root = SENTINEL_ROOT / skill_id
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        REPOSITORY_ROOT
                        / "skill-evaluator/scripts/validate_eval_suite.py"
                    ),
                    "contract",
                    str(root / "eval-spec.template.json"),
                    str(root / "scenarios.public.jsonl"),
                    str(root / "host-manifest.template.json"),
                    "--json",
                    "-",
                ],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["errors"], [])
            self.assertEqual(
                {warning["code"] for warning in report["warnings"]},
                {"non_ready.calibration", "non_ready.execution"},
            )

    def test_suite_quality_is_closed_without_tracked_holdout_or_ratings(self) -> None:
        for skill_id in SKILL_IDS:
            root = SENTINEL_ROOT / skill_id
            spec = load_json(root / "eval-spec.template.json", label="sentinel spec")
            quality = load_json(root / "suite-quality.json", label="suite quality")
            self.assertFalse(spec["execution"]["ready"])
            expected_headroom = 2
            self.assertEqual(
                spec["analysis"]["materiality"]["minimum_baseline_failure_cases"],
                expected_headroom,
            )
            definition = sentinel_builder.SKILLS[skill_id]
            self.assertLess(expected_headroom, len(definition["cases"]))
            minimum_interval_benefit = 0.0
            critical_gate = next(
                gate
                for gate in spec["hard_gates"]
                if gate["gate_id"] == "critical-benefit"
            )
            self.assertEqual(critical_gate["threshold"], minimum_interval_benefit)
            self.assertEqual(
                spec["analysis"]["estimands"][0]["minimum_benefit"],
                minimum_interval_benefit,
            )
            self.assertEqual(1, len(spec["analysis"]["estimands"]))
            model_grader = next(
                grader for grader in spec["graders"]
                if grader["type"] == "model"
            )
            process_check = next(
                check for check in model_grader["checks"]
                if check["check_id"] == "process-check"
            )
            self.assertEqual(
                process_check["required"],
                skill_id != "long-document-segmented-writing",
            )
            self.assertIsNone(spec["suite"]["holdout"])
            self.assertNotIn("calibration", spec["suite"])
            self.assertEqual(set(quality["gates"].values()), {"pass"})
            self.assertEqual(quality["calibration_hash"], None)
            self.assertTrue((root / "calibration-gold.jsonl").is_file())
            self.assertFalse((root / "calibration-ratings.jsonl").exists())
        names = {path.name for path in SENTINEL_ROOT.rglob("*") if path.is_file()}
        self.assertFalse(any("holdout" in name for name in names))

    def test_headroom_cases_bind_hidden_target_contracts(self) -> None:
        scenarios = {
            skill_id: [
                json.loads(line)
                for line in (
                    SENTINEL_ROOT / skill_id / "scenarios.public.jsonl"
                ).read_text().splitlines()
            ]
            for skill_id in (
                "long-document-segmented-writing",
                "skill-evaluator",
            )
        }
        long_tasks = {row["case_id"]: row for row in scenarios[
            "long-document-segmented-writing"
        ]}
        self.assertIn("bound compact ledger contract", long_tasks[
            "long-document-segmented-writing-compact-recovery"
        ]["execution_context"]["task"])
        self.assertEqual(
            ["fixtures/mode-selection.md"],
            [item["path"] for item in long_tasks[
                "long-document-segmented-writing-full-mode-selection"
            ]["fixture"]["initial_files"]],
        )
        evaluator_case = next(
            row for row in scenarios["skill-evaluator"]
            if row["case_id"] == "skill-evaluator-cli-schema-diagnosis"
        )
        self.assertEqual(
            ["fixtures/l0-spec.json"],
            [item["path"] for item in evaluator_case["fixture"]["initial_files"]],
        )
        for row in (*long_tasks.values(), evaluator_case):
            task = row["execution_context"]["task"]
            self.assertNotIn("Long Document Skill", task)
            self.assertNotIn("Skill Evaluator", task)

    def test_case_specific_grader_rules_are_exactly_scoped(self) -> None:
        expected = {
            "skill-evaluator": (
                "skill-evaluator-analyzer-exit-contract,",
                "skill-evaluator-protected-no-reviewer,",
                "skill-evaluator-analyzer-exit-contract-heldout,",
            ),
            "software-quality-workflows": (
                "software-quality-workflows-single-specialist-risk,",
                "software-quality-workflows-single-specialist-risk-heldout,",
            ),
            "writing-plans": (
                "writing-plans-explicit-handoff,",
                "writing-plans-explicit-handoff-heldout,",
            ),
        }
        for skill_id, rules in expected.items():
            prompt = (SENTINEL_ROOT / skill_id / "grader-prompt.md").read_text()
            self.assertIn("byte-for-byte equal to the full named ID", prompt)
            for rule in rules:
                self.assertIn(rule, prompt)

    def test_protected_planning_tasks_bind_the_patch_target(self) -> None:
        expected = {
            "software-quality-workflows": (
                "software-quality-workflows-protected-no-state",
                ("`fixtures/src/path.py`", "`tmp`", "`normalized_path`"),
            ),
            "writing-plans": (
                "writing-plans-protected-description",
                (
                    "`fixtures/agents/openai.yaml`",
                    "from 8.2.0 to 8.2.1",
                    "Preserve its full description verbatim",
                ),
            ),
        }
        for skill_id, (case_id, required_texts) in expected.items():
            path = SENTINEL_ROOT / skill_id / "scenarios.public.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            task = next(row for row in rows if row["case_id"] == case_id)[
                "execution_context"
            ]["task"]
            for required_text in required_texts:
                self.assertIn(required_text, task)

    def test_subject_versions_match_bundle_manifest(self) -> None:
        manifest = load_json(REPOSITORY_ROOT / "bundle-manifest.json", label="Bundle")
        versions = {row["id"]: row["version"] for row in manifest["skills"]}
        for skill_id, expected in versions.items():
            spec = load_json(
                SENTINEL_ROOT / skill_id / "eval-spec.template.json",
                label=f"{skill_id} sentinel spec",
            )
            self.assertEqual(expected, spec["subject"]["version"])

    def test_probe_set_is_inert_bounded_and_does_not_overclaim_direct_evidence(
        self,
    ) -> None:
        validate_document(self.probes, "interaction_probes")
        self.assertEqual(len(self.probes["probes"]), 6)
        capabilities = {row["capability"] for row in self.probes["probes"]}
        self.assertLessEqual(CRITICAL_PROBE_CAPABILITIES, capabilities)
        by_capability = {row["capability"]: row for row in self.probes["probes"]}
        self.assertIn(
            "direct.routing", by_capability["force_load"]["required_observations"]
        )
        self.assertIn(
            "direct.routing",
            by_capability["natural_routing"]["required_observations"],
        )
        natural = by_capability["natural_routing"]
        self.assertEqual(natural["fixture"]["path"], "scripts/codex_eval_host.py")
        self.assertGreater(
            (REPOSITORY_ROOT / natural["fixture"]["path"]).stat().st_size,
            32 * 1024,
        )
        self.assertIn("exactly seven ordered sections", natural["prompt"])
        self.assertIn("do not inspect other files", natural["prompt"])
        self.assertNotIn("$long-document-segmented-writing", natural["prompt"])
        self.assertIn(
            "permission.denied",
            by_capability["action_authorization_trace"]["required_observations"],
        )
        for row in self.probes["probes"]:
            self.assertEqual(row["network"], "denied")
            self.assertEqual(row["request_ceiling"], 1)
            self.assertNotIn("://", row["prompt"])

    def test_calibration_gold_uses_the_evaluator_semantic_owner(self) -> None:
        for skill_id in SKILL_IDS:
            root = SENTINEL_ROOT / skill_id
            path = root / "calibration-gold.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            spec = load_json(root / "eval-spec.template.json", label="sentinel spec")
            grader = next(item for item in spec["graders"] if item["type"] == "model")
            checks = {item["check_id"]: item for item in grader["checks"]}
            self.assertEqual(len(rows), 16)
            self.assertEqual(
                {row["check_id"] for row in rows},
                {"process-check", "quality-check"},
            )
            self.assertEqual(len({row["example_id"] for row in rows}), 16)
            self.assertEqual(
                {row["class"] for row in rows},
                {"known_good", "known_bad", "boundary", "abstain"},
            )
            for row in rows:
                self.assertEqual(
                    row["payload_hash"],
                    grader_semantics.semantic_payload_hash(row["payload"]),
                )
                self.assertEqual(
                    checks[row["check_id"]]["pass_condition"],
                    row["payload"]["check"]["pass_condition"],
                )
                exposed = json.dumps(
                    {
                        "example_id": row["example_id"],
                        "view": row["payload"]["view"],
                    },
                    sort_keys=True,
                ).lower()
                for label in ("known_good", "known_bad", "boundary", "abstain"):
                    self.assertNotIn(label, exposed)
            positive = [row for row in rows if row["class"] == "known_good"]
            self.assertEqual(len(positive), 4)
            for row in positive:
                candidate_evidence = row["payload"]["view"]["candidate_evidence"]
                if row["check_id"] == "quality-check":
                    self.assertIn("artifact", candidate_evidence)
                else:
                    self.assertIn("step 1", candidate_evidence)
                    self.assertIn("completed", candidate_evidence)
                    required_claims = sentinel_builder.SKILLS[skill_id]["claims"]
                    if row["example_id"].endswith("process-check-cal-05"):
                        required_claims = required_claims[:1]
                    for claim in required_claims:
                        self.assertIn(claim, candidate_evidence)
            process_boundaries = [
                row
                for row in rows
                if row["check_id"] == "process-check" and row["class"] == "boundary"
            ]
            self.assertEqual(len(process_boundaries), 2)
            for row in process_boundaries:
                candidate_evidence = row["payload"]["view"]["candidate_evidence"]
                self.assertIn("run_status=completed", candidate_evidence)
                self.assertIn("record_closed=true", candidate_evidence)
                self.assertIn("not_run", candidate_evidence)
            abstentions = [row for row in rows if row["class"] == "abstain"]
            self.assertEqual(len(abstentions), 4)
            for row in abstentions:
                candidate_evidence = row["payload"]["view"]["candidate_evidence"]
                self.assertTrue(
                    "truncated" in candidate_evidence
                    or "Conflicting" in candidate_evidence
                )
                self.assertIn("cannot", candidate_evidence)
            if skill_id == "software-quality-workflows":
                process_positive_two = next(
                    row
                    for row in rows
                    if row["example_id"].endswith("process-check-cal-05")
                )
                self.assertIn(
                    "`log_request`",
                    process_positive_two["payload"]["view"]["candidate_evidence"],
                )
            process_rows = [row for row in rows if row["check_id"] == "process-check"]
            for row in process_rows:
                task = row["payload"]["view"]["task"]
                self.assertIn("exactly the mechanisms required", task)
                required_claims = sentinel_builder.SKILLS[skill_id]["claims"]
                position = int(row["example_id"].rsplit("-", 1)[1])
                if position >= 5:
                    required_claims = required_claims[:1]
                for claim in required_claims:
                    self.assertIn(claim, task)
            quality_positive_two = next(
                row
                for row in rows
                if row["example_id"].endswith("quality-check-cal-05")
            )
            quality_evidence = quality_positive_two["payload"]["view"][
                "candidate_evidence"
            ]
            if skill_id == "skill-evaluator":
                quality_positive_one = next(
                    row
                    for row in rows
                    if row["example_id"].endswith("quality-check-cal-01")
                )
                quality_boundary_one = next(
                    row
                    for row in rows
                    if row["example_id"].endswith("quality-check-cal-03")
                )
                self.assertIn(
                    '"schema_version": 1',
                    quality_positive_one["payload"]["view"]["candidate_evidence"],
                )
                self.assertIn(
                    "does not preserve JSON syntax",
                    quality_boundary_one["payload"]["view"]["candidate_evidence"],
                )
                self.assertIn("validate_eval_suite.py", quality_evidence)
                self.assertIn("$SKILL_EVALUATOR_DIR", quality_evidence)
                self.assertIn("fixtures/l0-spec.json", quality_evidence)
                self.assertIn("single-spec", quality_evidence)
                self.assertIn("contract fixtures/l0-spec.json", quality_evidence)
                quality_negative_two = next(
                    row
                    for row in rows
                    if row["example_id"].endswith("quality-check-cal-06")
                )
                self.assertIn(
                    "two forbidden inputs for L0",
                    quality_negative_two["payload"]["view"]["candidate_evidence"],
                )
                self.assertIn(
                    "run_eval_plan.py",
                    quality_negative_two["payload"]["view"]["candidate_evidence"],
                )
            else:
                self.assertIn("evidence map", quality_evidence)
                self.assertIn(
                    "zero missing or contradictory requirements", quality_evidence
                )
            prompt = (root / grader["prompt"]["path"]).read_text()
            self.assertIn("only against relevant observable behavior", prompt)
            self.assertIn("task leaves irrelevant", prompt)
            self.assertIn("Treat bound task fixtures as supplied facts", prompt)
            self.assertIn("Judge each item independently", prompt)
            self.assertIn("Each `local-path-redacted` occurrence", prompt)
            self.assertIn("a following `/relative` suffix preserves", prompt)
            self.assertIn("exact-match patterns, and counts", prompt)
            self.assertIn("execution hygiene, not a separate workflow", prompt)
            self.assertIn("single target-Skill body is the intentional treatment delivery", prompt)
            self.assertIn("bound final artifact can directly demonstrate", prompt)
            self.assertIn("only when the task explicitly requires execution", prompt)
            self.assertIn("do not add a check or step absent from the task", prompt)
            if skill_id == "software-quality-workflows":
                self.assertIn("a team or role alone is insufficient", prompt)
                self.assertIn("syntax-only compilation is insufficient", prompt)
            elif skill_id == "long-document-segmented-writing":
                self.assertIn("Current recovery anchor", prompt)
                self.assertIn("compaction-resume", prompt)
                self.assertIn("intermediate recovery anchor", prompt)
                self.assertIn("four-field rule does not apply", prompt)
                self.assertIn("full-mode-selection", prompt)
                self.assertIn("ordered section drafts", prompt)
            elif skill_id == "skill-evaluator":
                self.assertIn("evaluator directory variable", prompt)
                self.assertIn("repository-relative substitute", prompt)
            elif skill_id == "writing-plans":
                self.assertIn("resolve each relative proof path", prompt)
                self.assertIn("raw substring exclusion", prompt)
                self.assertIn("exactly the version line", prompt)
                self.assertIn("invented file-shape requirement", prompt)
            self.assertIn("Within calibration items", prompt)
            self.assertIn("not an abstention", prompt)
            self.assertIn("`uncertainty` to `high`", prompt)
            for leaked_answer in (
                "validate_eval_suite.py",
                "exit `3`",
                "schema_version",
                "run_eval_plan.py",
            ):
                self.assertNotIn(leaked_answer, prompt)
            process_check = next(
                check for check in checks.values() if check["dimension"] == "process"
            )
            self.assertIn(
                "every Skill mechanism declared relevant",
                process_check["pass_condition"],
            )

    def test_deterministic_verifier_has_positive_and_negative_behavior(self) -> None:
        final_artifact = {
            "path": "workspace/final-answer-fixture.md",
            "sha256": "sha256:" + "1" * 64,
        }
        positive = {
            "terminal_status": "completed",
            "treatment_error": None,
            "protocol_error": None,
            "refusal": False,
            "timeout": False,
            "cleanup": {"status": "clean"},
            "actions": [],
            "state": [
                {
                    "checkpoint_id": "final-0",
                    "seq": 0,
                    "state_artifact": None,
                    "turn_id": "turn-1",
                }
            ],
            "handoffs": [],
            "artifacts": [final_artifact],
            "assertions": [
                {
                    "claim": "captured final Codex message",
                    "artifact": final_artifact,
                    "locally_verifiable": True,
                }
            ],
        }
        cases = [
            (positive, 0, True),
            ({**positive, "artifacts": [], "assertions": []}, 1, False),
            ({**positive, "cleanup": {"status": "dirty"}}, 1, False),
            (
                {
                    **positive,
                    "state": [
                        {
                            "checkpoint_id": "final-0",
                            "seq": 0,
                            "state_artifact": {"path": "state.json"},
                            "turn_id": "turn-1",
                        }
                    ],
                },
                1,
                False,
            ),
            ({**positive, "handoffs": [{"status": "requested"}]}, 1, False),
            (
                {**positive, "actions": [{"resolved_decision": "allow"}]},
                1,
                False,
            ),
        ]
        for skill_id in SKILL_IDS:
            verifier = SENTINEL_ROOT / skill_id / "verify.py"
            for result_json, expected_exit, expected_pass in cases:
                with (
                    self.subTest(skill_id=skill_id, expected_pass=expected_pass),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    workspace = Path(tmp)
                    (workspace / "result.json").write_text(
                        json.dumps(result_json), encoding="utf-8"
                    )
                    result = subprocess.run(
                        [sys.executable, str(verifier)],
                        cwd=workspace,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, expected_exit, result.stderr)
                    output = json.loads(result.stdout)
                    self.assertEqual(output["overall_pass"], expected_pass)
                    self.assertEqual(
                        {check["notes"] for check in output["checks"]}, {skill_id}
                    )
                    self.assertEqual([], output["missing_evidence"])
                    run_eval_plan._validate_grader_output(
                        output,
                        ["artifact-check", "safety-check"],
                    )
                    analyzer_artifacts = {
                        "result.json": {
                            "resolved": workspace / "result.json",
                            "encoding": "utf-8",
                            "lines": (workspace / "result.json")
                            .read_text(encoding="utf-8")
                            .splitlines(),
                        }
                    }
                    normalized = analyze_runs.validate_grader_output(
                        output,
                        [
                            {"check_id": "artifact-check", "required": True},
                            {"check_id": "safety-check", "required": True},
                        ],
                        analyzer_artifacts,
                    )
                    self.assertEqual(expected_pass, normalized["overall_pass"])


if __name__ == "__main__":
    unittest.main()
