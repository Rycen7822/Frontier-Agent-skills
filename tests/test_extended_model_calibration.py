from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _model_evolution_calibration import prepare_calibrations  # noqa: E402
from _model_evolution_contract import make_binding  # noqa: E402
import model_evolution as controller  # noqa: E402
from skill_evaluator_test_support import materialize_v5_calibration_inputs


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SENTINEL_ROOT = REPOSITORY_ROOT / "evaluation/model-evolution/sentinels"
EVALUATOR = REPOSITORY_ROOT / "skill-evaluator"
RUNNER = EVALUATOR / "scripts/run_model_calibration.py"
VALIDATOR = EVALUATOR / "scripts/validate_eval_suite.py"
FAKE_HOST = REPOSITORY_ROOT / "tests/fixtures/model_evolution/calibration-host.py"
SKILL_IDS = (
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
)


def _file_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _materialize(root: Path, skill_id: str) -> dict[str, Path]:
    fixture = materialize_v5_calibration_inputs(root / "fixture")
    target = root / "calibration"
    target.mkdir()
    source = SENTINEL_ROOT / skill_id
    for name in (
        "grader-output.schema.json",
        "grader-prompt.md",
        "scenarios.public.jsonl",
        "suite-quality.json",
    ):
        shutil.copy2(source / name, target / name)
    shutil.copy2(FAKE_HOST, target / "calibration-host.py")
    shutil.copy2(fixture["host"], target / "host.json")

    host = json.loads((target / "host.json").read_text())
    executable = Path(sys.executable).resolve()
    host["command"].update({
        "argv": [str(executable), str(target / "calibration-host.py")],
        "resolved_executable": str(executable),
        "executable_sha256": _file_hash(executable),
        "env_allowlist": [],
    })
    host["identity"]["host_build"] = _file_hash(target / "calibration-host.py")
    host["manifest_hash"] = "sha256:" + sha256(json.dumps(
        {key: value for key, value in host.items() if key != "manifest_hash"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()
    (target / "host.json").write_text(
        json.dumps(host, indent=2) + "\n",
        encoding="utf-8",
    )
    template = json.loads((source / "eval-spec.template.json").read_text())
    fixture_spec = json.loads(fixture["spec"].read_text())
    template["host"] = fixture_spec["host"]
    template["host"]["manifest"] = {
        "path": "host.json",
        "sha256": _file_hash(target / "host.json"),
    }
    template["suite"]["scenarios"] = {
        "path": "scenarios.public.jsonl",
        "sha256": _file_hash(target / "scenarios.public.jsonl"),
    }
    template["suite"]["public_scenarios"] = dict(
        template["suite"]["scenarios"],
    )
    template["suite"]["quality"] = {
        "path": "suite-quality.json",
        "sha256": _file_hash(target / "suite-quality.json"),
    }
    template["subject"]["claimed_hosts"] = [host["identity"]["host_id"]]
    template["execution"]["as_of"] = "2026-08-04T00:00:00Z"
    grader = next(item for item in template["graders"] if item["type"] == "model")
    grader["model"] = host["identity"]["execution"]["model"]
    (target / "spec.json").write_text(
        json.dumps(template, indent=2) + "\n",
        encoding="utf-8",
    )

    labels = []
    for line in (source / "calibration-gold.jsonl").read_text().splitlines():
        row = json.loads(line)
        row["host"] = host["identity"]["host_id"]
        row["model"] = grader["model"]
        labels.append(row)
    (target / "calibration-gold.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in labels
        ),
        encoding="utf-8",
    )
    return {
        "root": target,
        "spec": target / "spec.json",
        "host": target / "host.json",
        "labels": target / "calibration-gold.jsonl",
        "ratings": target / "run/calibration-ratings.jsonl",
        "calibration": target / "grader-calibration.json",
    }


def _runner_command(
    paths: dict[str, Path],
    *,
    max_workers: int | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(RUNNER),
        "--spec", str(paths["spec"]),
        "--labels", str(paths["labels"]),
        "--host", str(paths["host"]),
        "--output-dir", str(paths["root"] / "run"),
        "--created", "2026-08-04T00:00:00Z",
        "--expires", "2026-09-04T00:00:00Z",
        "--expected-requests", "16",
        "--host-timeout", "10",
    ]
    if max_workers is not None:
        command.extend(("--max-workers", str(max_workers)))
    return command


class ModelCalibrationLifecycleTests(unittest.TestCase):
    maxDiff = None

    def test_four_skill_calibration_closes_64_fake_requests_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            total = 0
            for skill_id in SKILL_IDS:
                paths = _materialize(base / skill_id, skill_id)
                command = _runner_command(paths, max_workers=4)
                first = subprocess.run(
                    command,
                    cwd=EVALUATOR,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, first.returncode, first.stdout + first.stderr)
                terminals = sorted((paths["root"] / "run/terminals").glob(
                    "*/terminal.json",
                ))
                self.assertEqual(16, len(terminals))
                before = {path.relative_to(paths["root"]): path.read_bytes() for path in terminals}
                second = subprocess.run(
                    command,
                    cwd=EVALUATOR,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, second.returncode, second.stdout + second.stderr)
                self.assertEqual(
                    before,
                    {path.relative_to(paths["root"]): path.read_bytes() for path in terminals},
                )
                validation = subprocess.run(
                    [
                        sys.executable,
                        str(VALIDATOR),
                        "calibration",
                        "--spec", str(paths["spec"]),
                        "--ratings", str(paths["ratings"]),
                        "--labels", str(paths["labels"]),
                        "--output", str(paths["calibration"]),
                    ],
                    cwd=EVALUATOR,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    0, validation.returncode, validation.stdout + validation.stderr,
                )
                calibration = json.loads(paths["calibration"].read_text())
                self.assertEqual(
                    {1.0},
                    {
                        metric["judge_to_gold_agreement"]
                        for metric in calibration["check_metrics"]
                    },
                )
                self.assertEqual(1, len(calibration["reviewers"]))
                campaign = {
                    "sentinel_index": make_binding(
                        REPOSITORY_ROOT
                        / "evaluation/model-evolution/sentinel-index-v1.json",
                        root="repository",
                        repository_root=REPOSITORY_ROOT,
                        campaign_root=paths["root"],
                    ),
                    "profiles": {
                        "target_observed": make_binding(
                            paths["host"],
                            root="campaign",
                            repository_root=REPOSITORY_ROOT,
                            campaign_root=paths["root"],
                        ),
                    },
                }
                controller._validate_evidence_join(
                    campaign,
                    role="grader_calibration",
                    skill_id=skill_id,
                    value=calibration,
                    repository_root=REPOSITORY_ROOT,
                    campaign_root=paths["root"],
                )
                total += len(terminals)
            self.assertEqual(64, total)

    def test_partial_terminal_blocks_before_any_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _materialize(Path(temporary), SKILL_IDS[0])
            partial = paths["root"] / "run/terminals/001"
            partial.mkdir(parents=True)
            result = subprocess.run(
                _runner_command(paths, max_workers=4),
                cwd=EVALUATOR,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("partial; refusing an unprovable replay", result.stderr)
            self.assertEqual([partial], list(partial.parent.iterdir()))
            self.assertFalse(paths["ratings"].exists())

    def test_completed_terminal_with_changed_identity_blocks_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _materialize(Path(temporary), SKILL_IDS[0])
            command = _runner_command(paths, max_workers=4)
            first = subprocess.run(
                command,
                cwd=EVALUATOR,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            terminals = sorted((paths["root"] / "run/terminals").glob(
                "*/terminal.json",
            ))
            before = {path: path.read_bytes() for path in terminals}
            labels = paths["labels"].read_text().splitlines()
            labels[0], labels[1] = labels[1], labels[0]
            paths["labels"].write_text("\n".join(labels) + "\n")

            second = subprocess.run(
                command,
                cwd=EVALUATOR,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, second.returncode)
            self.assertIn("terminal 1 identity differs", second.stderr)
            self.assertEqual(before, {path: path.read_bytes() for path in terminals})

    def test_invalid_label_identity_fails_before_creating_a_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = _materialize(Path(temporary), SKILL_IDS[0])
            labels = paths["labels"].read_text().splitlines()
            first = json.loads(labels[0])
            first["model"] = "wrong-model"
            labels[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
            paths["labels"].write_text("\n".join(labels) + "\n")
            result = subprocess.run(
                _runner_command(paths),
                cwd=EVALUATOR,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("differ from spec, model, or Host", result.stderr)
            self.assertFalse((paths["root"] / "run/terminals").exists())

    def test_controller_prepares_four_exact_no_overwrite_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = materialize_v5_calibration_inputs(base / "fixture")
            campaign_root = base / "campaign"
            campaign_root.mkdir()
            host_path = campaign_root / "target-host.json"
            shutil.copy2(fixture["host"], host_path)
            host = json.loads(host_path.read_text())
            host["command"]["argv"].extend(["--timeout", "10"])
            host["manifest_hash"] = "sha256:" + sha256(json.dumps(
                {
                    key: value
                    for key, value in host.items()
                    if key != "manifest_hash"
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()).hexdigest()
            host_path.write_text(json.dumps(host, indent=2) + "\n")
            sentinel_path = (
                REPOSITORY_ROOT / "evaluation/model-evolution/sentinel-index-v1.json"
            )
            campaign = {
                "campaign_id": "calibration-preparation-fixture",
                "campaign_hash": "sha256:" + "1" * 64,
                "state_revision": 4,
                "phase": "target_profile_ready",
                "sentinel_index": make_binding(
                    sentinel_path,
                    root="repository",
                    repository_root=REPOSITORY_ROOT,
                    campaign_root=campaign_root,
                ),
                "profiles": {
                    "target_observed": make_binding(
                        host_path,
                        root="campaign",
                        repository_root=REPOSITORY_ROOT,
                        campaign_root=campaign_root,
                    ),
                },
            }
            prepared = prepare_calibrations(
                repository_root=REPOSITORY_ROOT,
                campaign_root=campaign_root,
                campaign=campaign,
                as_of="2026-08-04T00:00:00Z",
                created="2026-08-04T00:00:00Z",
                expires="2026-09-04T00:00:00Z",
                max_workers=4,
            )
            self.assertEqual(list(SKILL_IDS), [
                item["skill_id"] for item in prepared["commands"]
            ])
            self.assertEqual([4, 5, 6, 7], [
                int(item["record"][item["record"].index("--expected-revision") + 1])
                for item in prepared["commands"]
            ])
            before = (campaign_root / "calibration/preparation.json").read_bytes()
            repeated = prepare_calibrations(
                repository_root=REPOSITORY_ROOT,
                campaign_root=campaign_root,
                campaign=campaign,
                as_of="2026-08-04T00:00:00Z",
                created="2026-08-04T00:00:00Z",
                expires="2026-09-04T00:00:00Z",
                max_workers=4,
            )
            self.assertEqual(prepared, repeated)
            self.assertEqual(
                before,
                (campaign_root / "calibration/preparation.json").read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
