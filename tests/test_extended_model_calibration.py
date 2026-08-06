from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "skill-evaluator/scripts"),
)

from _model_evolution_calibration import (  # noqa: E402
    CalibrationPreparationError,
    close_calibration_failure,
    prepare_calibrations,
)
from _model_evolution_calibration_receipt import (  # noqa: E402
    CalibrationReceiptError,
    _verify_preparation_lineage,
    close_calibration_rejection,
    validate_calibration_rejection_receipt,
)
from _model_evolution_contract import (  # noqa: E402
    make_binding,
    self_hash,
    validate_document,
    with_self_hash,
)
from _model_evolution_qualification import project_qualification  # noqa: E402
import model_evolution as controller  # noqa: E402
import run_model_calibration as calibration_runner  # noqa: E402
from support.model_evolution.host import materialize_campaign  # noqa: E402
from support.model_evolution.documents import host_manifest  # noqa: E402
from support.model_evolution.repository import write_json  # noqa: E402


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SENTINEL_ROOT = REPOSITORY_ROOT / "evaluation/model-evolution/sentinels"
EVALUATOR = REPOSITORY_ROOT / "skill-evaluator"
EVALUATOR_FIXTURES = REPOSITORY_ROOT / "tests/fixtures/skill_evaluator"
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
    host = host_manifest()
    executable = Path(sys.executable).resolve()
    host["command"].update({
        "argv": [str(executable), str(target / "calibration-host.py")],
        "resolved_executable": str(executable),
        "executable_sha256": _file_hash(executable),
        "env_allowlist": [],
    })
    host["identity"]["host_build"] = _file_hash(target / "calibration-host.py")
    host["manifest_hash"] = self_hash(host, "manifest_hash")
    (target / "host.json").write_text(
        json.dumps(host, indent=2) + "\n",
        encoding="utf-8",
    )
    template = json.loads((source / "eval-spec.template.json").read_text())
    fixture_spec = json.loads((EVALUATOR_FIXTURES / "spec-v5.json").read_text())
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
    def test_calibration_host_uses_only_the_declared_transport_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = _materialize(Path(raw), "writing-plans")
            host = json.loads(paths["host"].read_text())
            host["command"]["env_allowlist"] = [
                "HTTP_PROXY",
                "PYTHONDONTWRITEBYTECODE",
            ]
            with mock.patch.dict(
                os.environ,
                {
                    "HTTP_PROXY": "http://proxy.invalid:8080",
                    "UNDECLARED_SECRET": "must-not-pass",
                },
                clear=True,
            ):
                _, environment = calibration_runner._host_command(
                    host,
                    paths["spec"].parent,
                )
            self.assertEqual(
                {
                    "HTTP_PROXY": "http://proxy.invalid:8080",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                environment,
            )

    def test_pre_turn_failure_receipt_is_canonical_and_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = materialize_campaign(Path(raw))
            campaign = fixture["campaign"]
            campaign_root = fixture["campaign_root"]
            write_json(
                campaign_root / "qualification/qualification.json",
                project_qualification(
                    campaign,
                    repository_root=fixture["repository_root"],
                    campaign_root=campaign_root,
                    observed_as_of="2026-08-03T00:00:00Z",
                    valid_until="2026-08-04T00:00:00Z",
                ),
            )
            preparation = with_self_hash({
                "schema_version": "model-evolution-calibration-preparation/1",
                "campaign_id": campaign["campaign_id"],
                "campaign_hash": campaign["campaign_hash"],
                "state_revision": campaign["state_revision"],
                "as_of": "2026-08-03T00:00:00Z",
                "created": "2026-08-03T00:00:00Z",
                "expires": "2026-08-04T00:00:00Z",
                "commands": [{
                    "skill_id": "writing-plans",
                    "request_count": 1,
                    "run": [],
                    "validate": [],
                    "record": [],
                }],
            }, "preparation_hash")
            write_json(
                campaign_root / "calibration/preparation.json",
                preparation,
            )
            terminal_root = (
                campaign_root
                / "calibration/writing-plans/run/terminals/001"
            )
            terminal_root.mkdir(parents=True)
            result = {
                "actions": [],
                "artifacts": [],
                "assertions": [],
                "cleanup": {"status": "clean"},
                "context": {"bytes": 0},
                "envelope": {
                    "entry_id": "writing-plans-calibration-01",
                    "entry_ordinal": 0,
                    "request_kind": "model_grade",
                },
                "failure_class": "model_task_timeout",
                "handoffs": [],
                "principals": [],
                "record_type": "skill-evaluator-host-result/1",
                "request_hash": "sha256:" + "2" * 64,
                "state": [],
                "terminal": True,
                "terminal_status": "timeout",
                "usage": {"records": []},
            }
            (terminal_root / "host-stdout.jsonl").write_text(
                json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            stderr = terminal_root / "host-stderr.txt"
            stderr.write_text("transport unavailable\n", encoding="utf-8")
            output = campaign_root / "calibration/failure-writing-plans.json"
            receipt = close_calibration_failure(
                repository_root=fixture["repository_root"],
                campaign_root=campaign_root,
                campaign=campaign,
                skill_id="writing-plans",
                output=output,
            )
            validate_document(receipt, "failure_receipt")
            self.assertEqual(1, receipt["request_count"])
            self.assertEqual({"timeout": 1, "failed": 0}, receipt["outcomes"])
            self.assertEqual(
                receipt,
                close_calibration_failure(
                    repository_root=fixture["repository_root"],
                    campaign_root=campaign_root,
                    campaign=campaign,
                    skill_id="writing-plans",
                    output=output,
                ),
            )
            original = output.read_bytes()
            stderr.write_text("changed evidence\n", encoding="utf-8")
            with self.assertRaisesRegex(
                CalibrationPreparationError,
                "refusing to replace different calibration bytes",
            ):
                close_calibration_failure(
                    repository_root=fixture["repository_root"],
                    campaign_root=campaign_root,
                    campaign=campaign,
                    skill_id="writing-plans",
                    output=output,
                )
            self.assertEqual(original, output.read_bytes())

    def test_completed_threshold_rejection_receipt_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = materialize_campaign(Path(raw))
            campaign = fixture["campaign"]
            campaign_root = fixture["campaign_root"]
            write_json(
                campaign_root / "qualification/qualification.json",
                project_qualification(
                    campaign,
                    repository_root=fixture["repository_root"],
                    campaign_root=campaign_root,
                    observed_as_of="2026-08-03T00:00:00Z",
                    valid_until="2026-08-04T00:00:00Z",
                ),
            )
            preparation = with_self_hash({
                "schema_version": "model-evolution-calibration-preparation/1",
                "campaign_id": campaign["campaign_id"],
                "campaign_hash": campaign["campaign_hash"],
                "state_revision": campaign["state_revision"],
                "as_of": "2026-08-03T00:00:00Z",
                "created": "2026-08-03T00:00:00Z",
                "expires": "2026-08-04T00:00:00Z",
                "commands": [{
                    "skill_id": "writing-plans",
                    "request_count": 1,
                    "run": [],
                    "validate": [],
                    "record": [],
                }],
            }, "preparation_hash")
            write_json(campaign_root / "calibration/preparation.json", preparation)
            skill_root = campaign_root / "calibration/writing-plans"
            terminal_root = skill_root / "run/terminals/001"
            terminal_root.mkdir(parents=True)
            payload_hash = "sha256:" + "4" * 64
            request_hash = "sha256:" + "5" * 64
            example_id = "writing-plans-quality-check-cal-01"
            host_result = {
                "cleanup": {"state": "not_applicable", "status": "clean"},
                "envelope": {
                    "entry_id": example_id,
                    "entry_ordinal": 0,
                    "request_kind": "model_grade",
                },
                "protocol_error": None,
                "record_type": "skill-evaluator-host-result/1",
                "refusal": False,
                "request_hash": request_hash,
                "terminal": True,
                "terminal_status": "completed",
                "timeout": False,
                "treatment_error": None,
            }
            (terminal_root / "host-stdout.jsonl").write_text(
                json.dumps(host_result, sort_keys=True, separators=(",", ":"))
                + "\n",
                encoding="utf-8",
            )
            terminal = with_self_hash({
                "schema_version": "model-calibration-terminal/1",
                "example_id": example_id,
                "check_id": "quality-check",
                "host_result_hash": "sha256:" + "6" * 64,
                "label": "abstain",
                "notes": "Evidence is insufficient.",
                "payload_hash": payload_hash,
                "position": 1,
                "request_hash": request_hash,
                "severity": 0,
                "uncertainty": "high",
            }, "terminal_hash")
            write_json(terminal_root / "terminal.json", terminal)
            label = {
                "example_id": example_id,
                "check_id": "quality-check",
                "payload_hash": payload_hash,
                "gold_label": "pass",
            }
            rating = {
                "example_id": example_id,
                "check_id": "quality-check",
                "payload_hash": payload_hash,
                "label": "abstain",
                "position": 1,
                "thresholds": {
                    "minimum_agreement": 1.0,
                    "minimum_examples": 1,
                },
            }
            for path, row in (
                (skill_root / "calibration-gold.jsonl", label),
                (skill_root / "run/calibration-ratings.jsonl", rating),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
            output = campaign_root / "calibration/rejection-writing-plans.json"
            receipt = close_calibration_rejection(
                repository_root=fixture["repository_root"],
                campaign_root=campaign_root,
                campaign=campaign,
                skill_id="writing-plans",
                output=output,
            )
            validate_document(receipt, "calibration_rejection_receipt")
            self.assertEqual(1, receipt["request_count"])
            self.assertEqual(["quality-check"], receipt["failed_checks"])
            self.assertEqual(0.0, receipt["check_metrics"][0]["agreement"])
            self.assertEqual(
                1,
                validate_calibration_rejection_receipt(
                    make_binding(
                        output,
                        root="campaign",
                        repository_root=fixture["repository_root"],
                        campaign_root=campaign_root,
                    ),
                    repository_root=fixture["repository_root"],
                    campaign_root=campaign_root,
                    campaign=campaign,
                ),
            )
            self.assertEqual(
                receipt,
                close_calibration_rejection(
                    repository_root=fixture["repository_root"],
                    campaign_root=campaign_root,
                    campaign=campaign,
                    skill_id="writing-plans",
                    output=output,
                ),
            )

    def test_rejection_lineage_allows_only_prior_calibration_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = materialize_campaign(Path(raw))["campaign"]
            campaign["phase"] = "target_profile_ready"
            campaign = with_self_hash(campaign, "campaign_hash")
            preparation = with_self_hash({
                "campaign_id": campaign["campaign_id"],
                "campaign_hash": campaign["campaign_hash"],
                "state_revision": campaign["state_revision"],
                "commands": [
                    {"skill_id": skill_id, "request_count": 16}
                    for skill_id in SKILL_IDS
                ],
            }, "preparation_hash")
            campaign["skill_evidence"][SKILL_IDS[0]]["grader_calibration"] = {
                "path": "calibration/first.json",
                "root": "campaign",
                "sha256": "sha256:" + "7" * 64,
            }
            campaign["budgets"]["observed"]["model_grade"] = 16
            campaign["budgets"]["observed"]["provider_requests"] = 16
            campaign["state_revision"] += 1
            campaign = with_self_hash(campaign, "campaign_hash")
            _verify_preparation_lineage(campaign, preparation)

            campaign["budgets"]["observed"]["model_grade"] += 1
            campaign = with_self_hash(campaign, "campaign_hash")
            with self.assertRaisesRegex(
                CalibrationReceiptError,
                "calibration ancestry differs",
            ):
                _verify_preparation_lineage(campaign, preparation)

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
            campaign_root = base / "campaign"
            campaign_root.mkdir()
            host_path = campaign_root / "target-host.json"
            host = host_manifest()
            host["command"]["argv"].extend(["--timeout", "10"])
            write_json(host_path, {**host, "manifest_hash": self_hash(host, "manifest_hash")})
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
