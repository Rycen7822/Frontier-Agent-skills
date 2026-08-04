from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "skill-evaluator/scripts"))

import grader_semantics  # noqa: E402
import build_model_evolution_sentinels as sentinels  # noqa: E402
from _model_evolution_contract import (  # noqa: E402
    CRITICAL_PROBE_CAPABILITIES,
    SKILL_IDS,
    load_json,
    resolve_binding,
    validate_document,
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
                self.assertGreaterEqual(len(task.split()), 20)
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
            self.assertIsNone(spec["suite"]["holdout"])
            self.assertNotIn("calibration", spec["suite"])
            self.assertEqual(set(quality["gates"].values()), {"pass"})
            self.assertEqual(quality["calibration_hash"], None)
            self.assertTrue((root / "calibration-gold.jsonl").is_file())
            self.assertFalse((root / "calibration-ratings.jsonl").exists())
        names = {path.name for path in SENTINEL_ROOT.rglob("*") if path.is_file()}
        self.assertFalse(any("holdout" in name for name in names))

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
                    self.assertIn("verification", candidate_evidence)
                    self.assertTrue(
                        "artifact" in candidate_evidence
                        or "final result" in candidate_evidence
                    )
                else:
                    self.assertIn("step 1", candidate_evidence)
                    self.assertIn("completed", candidate_evidence)
                    for claim in sentinels.SKILLS[skill_id]["claims"]:
                        self.assertIn(claim, candidate_evidence)
            process_boundaries = [
                row
                for row in rows
                if row["check_id"] == "process-check"
                and row["class"] == "boundary"
            ]
            self.assertEqual(len(process_boundaries), 2)
            for row in process_boundaries:
                candidate_evidence = row["payload"]["view"]["candidate_evidence"]
                self.assertIn("run_status=completed", candidate_evidence)
                self.assertIn("record_closed=true", candidate_evidence)
                self.assertIn("not_run", candidate_evidence)
            prompt = (root / grader["prompt"]["path"]).read_text()
            self.assertIn("only against the declared mechanism relevant", prompt)
            self.assertIn("do not require unrelated mechanisms", prompt)
            self.assertIn("`uncertainty` to `high`", prompt)

    def test_deterministic_verifier_has_positive_and_negative_behavior(self) -> None:
        verifier = SENTINEL_ROOT / SKILL_IDS[0] / "verify.py"
        cases = [
            (
                {
                    "terminal_status": "completed",
                    "treatment_error": None,
                    "artifacts": [{"path": "final.md"}],
                },
                0,
                True,
            ),
            (
                {
                    "terminal_status": "failed",
                    "treatment_error": "fixture failure",
                    "artifacts": [],
                },
                1,
                False,
            ),
        ]
        for result_json, expected_exit, expected_pass in cases:
            with (
                self.subTest(expected_pass=expected_pass),
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
                self.assertEqual(
                    json.loads(result.stdout)["overall_pass"], expected_pass
                )


if __name__ == "__main__":
    unittest.main()
