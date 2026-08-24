from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _model_evolution_campaign import qualification_request_ceilings  # noqa: E402
from _model_evolution_confirmatory_v3_builder import (  # noqa: E402
    OUTPUT_ROOT,
    SOURCE_PATH,
    _normalize,
    _validate_source,
)
from _model_evolution_contract import validate_document  # noqa: E402
from model_evolution import CliError, _require_initializable_sentinel  # noqa: E402
from _model_evolution_state import (  # noqa: E402
    StateError,
    record_evidence,
    register_plan,
)


ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
INDEX_PATH = ROOT / OUTPUT_ROOT / "sentinel-index-v3.json"
OLD_INDEX_PATH = (
    ROOT / "evaluation/model-evolution/confirmatory-v1/sentinel-index-v3.json"
)
POLICY_PATH = (
    ROOT / "evaluation/model-evolution/confirmatory-v2/apparatus-retry-policy-v1.json"
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture_payloads(index_path: Path) -> list[str]:
    index = _json(index_path)
    scenarios_path = ROOT / index["skills"]["skill-evaluator"]["public_scenarios"]["path"]
    scenarios = [json.loads(line) for line in scenarios_path.read_text().splitlines()]
    payloads = []
    for scenario in scenarios:
        fixture = scenarios_path.parent / scenario["fixture"]["initial_files"][0]["path"]
        payloads.append(fixture.read_text(encoding="utf-8"))
    return payloads


def _old_normalized(payload: str) -> str:
    lines = []
    for line in payload.splitlines():
        if line.startswith((
            "Prompt marker:", "Independent marker:", "Case ID:", "Fixture path:"
        )):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


class ConfirmatoryCorpusV3(unittest.TestCase):
    def test_source_has_48_independent_source_bound_cases(self) -> None:
        source = _json(ROOT / SOURCE_PATH)
        cases = _validate_source(source, ROOT)
        self.assertEqual(48, len(cases))
        facts = {
            json.dumps(_normalize(row["fact_signature"]), sort_keys=True)
            for row in cases
        }
        payloads = {
            json.dumps(_normalize({
                "fixture": row["fixture"],
                "expected_semantics": row["expected_semantics"],
                "protected_boundary": row["protected_boundary"],
            }), sort_keys=True)
            for row in cases
        }
        self.assertEqual(48, len(facts))
        self.assertEqual(48, len(payloads))
        strata = {row["stratum"] for row in cases}
        self.assertEqual(6, len(strata))
        for stratum in strata:
            members = [row for row in cases if row["stratum"] == stratum]
            self.assertEqual(8, len(members))
            self.assertEqual(4, sum(row["input_shape"] == "ordinary" for row in members))
            self.assertEqual(4, sum(row["input_shape"] == "boundary" for row in members))

    def test_marker_renaming_and_counterfactual_calibration(self) -> None:
        source = _json(ROOT / SOURCE_PATH)
        row = {
            "fixture": source["cases"][0]["fixture"],
            "expected_semantics": source["cases"][0]["expected_semantics"],
            "protected_boundary": source["cases"][0]["protected_boundary"],
        }
        renamed = copy.deepcopy(row)
        renamed["prompt_marker"] = "renamed-marker"
        renamed["case_id"] = "renamed-case"
        renamed["fixture_path"] = "renamed/path.md"
        self.assertEqual(
            _normalize(row),
            _normalize(renamed),
        )
        for case in source["cases"]:
            self.assertNotEqual(
                case["fact_signature"]["expected_disposition"],
                case["counterfactual"]["resulting_disposition"],
            )

    def test_v1_is_historical_diagnostic_and_cannot_initialize(self) -> None:
        self.assertEqual(48, len(_fixture_payloads(OLD_INDEX_PATH)))
        self.assertEqual(12, len({_old_normalized(row) for row in _fixture_payloads(OLD_INDEX_PATH)}))
        old_index = _json(OLD_INDEX_PATH)
        with self.assertRaisesRegex(CliError, "historical diagnostic"):
            _require_initializable_sentinel(old_index)
        _require_initializable_sentinel(_json(INDEX_PATH))

    def test_generated_index_is_complete_treatment_blind_and_budget_stable(self) -> None:
        index = _json(INDEX_PATH)
        validate_document(index, "sentinel_index")
        paths = {ROOT / binding["path"] for binding in index["catalog_files"]}
        actual = {
            path for path in INDEX_PATH.parent.rglob("*")
            if path.is_file() and path != INDEX_PATH
        }
        self.assertEqual(actual, paths)
        spec = _json(ROOT / index["skills"]["skill-evaluator"]["spec_template"]["path"])
        self.assertEqual({"arm-17", "arm-42"}, {row["treatment_id"] for row in spec["treatments"]})
        self.assertEqual(1, len({json.dumps(row["checks"], sort_keys=True) for row in spec["graders"] if row["type"] == "model"}))
        policy = _json(POLICY_PATH)
        ceilings = qualification_request_ceilings(
            index,
            repository_root=ROOT,
            campaign_root=ROOT,
            probe_count=6,
            apparatus_policy=policy,
        )
        self.assertEqual(
            {"provider_requests": 2204, "execute": 1032, "model_grade": 1160,
             "calibration": 64, "calibration_attempts": 128},
            {key: ceilings[key] for key in (
                "provider_requests", "execute", "model_grade",
                "calibration", "calibration_attempts",
            )},
        )

    def test_builder_replay_is_deterministic(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/build_model_evolution_confirmatory_v3.py", "--check"],
            cwd=ROOT, env=ENV, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        copied = ROOT / OUTPUT_ROOT / "skill-evaluator-authoring-source-v3.json"
        self.assertEqual(
            hashlib.sha256((ROOT / SOURCE_PATH).read_bytes()).digest(),
            hashlib.sha256(copied.read_bytes()).digest(),
        )

    def test_se_first_revision_gate_is_exact_and_keeps_other_lanes_closed(self) -> None:
        skill_evidence = {
            skill_id: {
                "grader_calibration": {"root": "campaign"},
                "current_summary": None,
                "revision_report": None,
            }
            for skill_id in (
                "long-document-segmented-writing", "skill-evaluator",
                "software-quality-workflows", "writing-plans",
            )
        }
        skill_evidence["skill-evaluator"]["current_summary"] = {
            "root": "campaign", "path": "analysis/current/se/summary.json"
        }
        current_plan = {
            "role": "target_current", "skill_id": "skill-evaluator",
            "plan": {"root": "campaign", "path": "current/se/plan.json"},
            "plan_digest": "sha256:" + "1" * 64,
            "execute_ceiling": 288, "model_grade_ceiling": 288,
        }
        state = {
            "phase": "calibration_ready", "state_revision": 12,
            "candidate": None, "profiles": {"predecessor": None},
            "sentinel_index": {
                "root": "campaign",
                "path": "evaluation/model-evolution/confirmatory-v3/sentinel-index-v3.json",
            },
            "plans": [current_plan], "skill_evidence": skill_evidence,
            "budgets": {
                "ceiling": {"execute": 1032, "model_grade": 1160,
                            "provider_requests": 2204},
                "reserved": {"execute": 444, "model_grade": 572,
                             "provider_requests": 1028},
            },
        }
        prior_plan = {
            **current_plan,
            "role": "target_prior",
            "plan": {"root": "campaign", "path": "prior/se/plan.json"},
            "plan_digest": "sha256:" + "2" * 64,
        }
        register_plan(state, prior_plan)
        self.assertEqual("calibration_ready", state["phase"])
        record_evidence(
            state, role="revision_report", skill_id="skill-evaluator",
            binding={"root": "campaign", "path": "reports/se.json"},
        )
        self.assertEqual("calibration_ready", state["phase"])
        self.assertIsNone(
            state["skill_evidence"]["long-document-segmented-writing"]["current_summary"]
        )

        wrong = copy.deepcopy(state)
        wrong["skill_evidence"]["skill-evaluator"]["revision_report"] = None
        wrong["sentinel_index"]["path"] = (
            "evaluation/model-evolution/confirmatory-v1/sentinel-index-v3.json"
        )
        with self.assertRaises(StateError):
            record_evidence(
                wrong, role="revision_report", skill_id="skill-evaluator",
                binding={"root": "campaign", "path": "reports/rejected.json"},
            )

    def test_deterministic_oracle_treats_synonymous_rationales_consistently(self) -> None:
        case = next(
            row for row in _json(ROOT / SOURCE_PATH)["cases"]
            if row["case_id"] == "D23-AB-01"
        )
        result = {
            "envelope": {
                "entry_id": "entry.skill-evaluator-confirmatory-v3-ab-01.arm-17.r1"
            },
            "terminal_status": "completed",
            "treatment_error": None,
            "protocol_error": None,
            "refusal": False,
            "timeout": False,
            "cleanup": {"status": "clean"},
            "actions": [],
            "state": [],
            "handoffs": [],
            "artifacts": [
                {"path": path} for path in (
                    "workspace/final-answer.md",
                    "workspace/turn-answers.json",
                    "workspace/command-trace.json",
                    "workspace/workspace-evidence.json",
                    "workspace/host-observation.json",
                )
            ],
            "assertions": [{
                "claim": "captured final Codex message",
                "locally_verifiable": True,
                "artifact": {"path": "workspace/final-answer.md"},
            }],
        }
        answer = {
            "case_id": case["case_id"],
            "owner": case["fact_signature"]["controlling_owner"],
            "oracle_result": case["deterministic_oracle"]["expected"],
            "disposition": "apply the frozen evaluation contract",
            "boundary_preserved": True,
            "rationale": "The controlling owner fixes the allowed action and effects.",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
            for name in ("verify.py", "verify_common.py"):
                source = ROOT / OUTPUT_ROOT / "sentinels/skill-evaluator" / name
                (root / name).write_bytes(source.read_bytes())
            for rationale in (
                answer["rationale"],
                "Because the frozen owner defines both the action and its permitted effects.",
            ):
                answer["rationale"] = rationale
                (workspace / "final-answer.md").write_text(
                    json.dumps(answer), encoding="utf-8"
                )
                completed = subprocess.run(
                    [sys.executable, "-B", "verify.py"], cwd=root, env=ENV,
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
                self.assertTrue(json.loads(completed.stdout)["overall_pass"])


if __name__ == "__main__":
    unittest.main()
