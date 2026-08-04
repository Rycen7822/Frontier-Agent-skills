from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from model_evolution_test_support import materialize_campaign  # noqa: E402

from _model_evolution_contract import verify_self_hash  # noqa: E402
from _model_evolution_contract import canonical_bytes, content_hash  # noqa: E402
from _model_evolution_holdout import _load_holdout_bundle  # noqa: E402
from _model_evolution_materialization import (  # noqa: E402
    MaterializationError,
    _assert_tree_equal,
    _relative_path,
    prepare_current_plan,
    promoted_model_grading_host,
)


class ModelEvolutionMaterializationTests(unittest.TestCase):
    def test_promoted_host_binds_calibration_and_final_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = materialize_campaign(Path(raw))
            host = copy.deepcopy(
                json.loads(fixture["paths"]["host"].read_text(encoding="utf-8"))
            )
            final = fixture["campaign_root"] / "current-plans/skill/host.json"
            promoted = promoted_model_grading_host(
                host,
                host_path=final,
                calibration_file_hash="sha256:" + "1" * 64,
            )

            capability = promoted["capabilities"][-1]
            self.assertEqual(capability["capability"], "model_grading")
            self.assertEqual(capability["probe"]["status"], "pass")
            self.assertEqual(
                capability["probe"]["artifact"]["path"],
                "grader-calibration.json",
            )
            argv = promoted["command"]["argv"]
            self.assertEqual(argv[argv.index("--host-manifest") + 1], str(final))
            verify_self_hash(promoted, "manifest_hash")

            with self.assertRaisesRegex(MaterializationError, "already owns"):
                promoted_model_grading_host(
                    promoted,
                    host_path=final,
                    calibration_file_hash="sha256:" + "1" * 64,
                )

    def test_paths_and_phase_fail_closed(self) -> None:
        for value in ("../escape", "/absolute", "not//normalized"):
            with self.subTest(value=value), self.assertRaises(MaterializationError):
                _relative_path(value, label="fixture")

        with tempfile.TemporaryDirectory() as raw:
            fixture = materialize_campaign(Path(raw))
            with self.assertRaisesRegex(MaterializationError, "calibration_ready"):
                prepare_current_plan(
                    repository_root=fixture["repository_root"],
                    campaign_root=fixture["campaign_root"],
                    campaign=fixture["campaign"],
                    skill_id="writing-plans",
                )

    def test_exact_tree_comparison_rejects_symlink_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            expected = root / "expected"
            observed = root / "observed"
            expected.mkdir()
            observed.mkdir()
            expected_file = expected / "plan.json"
            expected_file.write_text("{}", encoding="utf-8")
            (observed / "plan.json").symlink_to(expected_file)

            with self.assertRaisesRegex(MaterializationError, "symlink"):
                _assert_tree_equal(observed, expected, label="formal plan")

    def test_holdout_bundle_requires_positive_and_protected_scenarios(self) -> None:
        root = SCRIPTS.parent
        source = root / (
            "evaluation/model-evolution/sentinels/writing-plans/"
            "scenarios.public.jsonl"
        )
        public = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
        ]
        positive = copy.deepcopy(public[0])
        protected = copy.deepcopy(
            next(row for row in public if "protected" in row["tags"])
        )
        rows = []
        for row, suffix, task, tags in (
            (
                positive,
                "positive",
                "Create a plan for a newly supplied two-module migration.",
                {"heldout"},
            ),
            (
                protected,
                "protected",
                "Describe the boundary without starting implementation.",
                {"heldout", "protected", "boundary"},
            ),
        ):
            row["case_id"] = f"writing-plans-heldout-{suffix}"
            row["split"] = "heldout"
            row["attribution_evaluable"] = True
            row["tags"] = sorted(set(row["tags"]) | tags)
            row["execution_context"]["task"] = task
            row["turns"][0]["input"]["content"] = task
            rows.append(row)

        with tempfile.TemporaryDirectory() as raw:
            bundle = Path(raw)
            payload = bundle / "scenarios.heldout.jsonl"
            payload.write_bytes(
                b"".join(canonical_bytes(row) + b"\n" for row in rows)
            )
            proof = {
                "case_classes": [
                    {"case_id": rows[0]["case_id"], "class": "positive"},
                    {
                        "case_id": rows[1]["case_id"],
                        "class": "boundary_or_failure",
                    },
                ]
            }
            (bundle / "suite-quality-proof.json").write_bytes(
                canonical_bytes(proof)
            )
            manifest = {
                "schema_version": 1,
                "external_holdout_contract_id": (
                    "writing-plans-external-holdout-v1"
                ),
                "skill_id": "writing-plans",
                "payload_file": payload.name,
                "payload_sha256": content_hash(payload.read_bytes()),
                "scenario_count": 2,
                "scenario_ids": [row["case_id"] for row in rows],
                "scenarios": [
                    {
                        "case_id": row["case_id"],
                        "scenario_sha256": content_hash(canonical_bytes(row)),
                        "risk": row["risk"],
                        "tags": row["tags"],
                    }
                    for row in rows
                ],
                "custodian": "independent-evaluation-owner",
                "exposure_status": "exposed",
                "refresh_state": "fresh",
            }
            (bundle / "holdout-manifest.json").write_bytes(
                canonical_bytes(manifest)
            )
            _, observed, _ = _load_holdout_bundle(
                bundle,
                skill_id="writing-plans",
                contract_id="writing-plans-external-holdout-v1",
                case_ceiling=2,
                public_rows=public,
            )
            self.assertEqual([row["case_id"] for row in observed], manifest["scenario_ids"])

            proof["case_classes"][1]["class"] = "positive"
            (bundle / "suite-quality-proof.json").write_bytes(canonical_bytes(proof))
            with self.assertRaisesRegex(MaterializationError, "positive/protected"):
                _load_holdout_bundle(
                    bundle,
                    skill_id="writing-plans",
                    contract_id="writing-plans-external-holdout-v1",
                    case_ceiling=2,
                    public_rows=public,
                )


if __name__ == "__main__":
    unittest.main()
