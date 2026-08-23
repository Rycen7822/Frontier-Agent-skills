from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "evaluation" / "model-evolution" / "sentinel_sources"))

from _model_evolution_contract import ContractError  # noqa: E402
from _model_evolution_qualification import _apparatus_artifact  # noqa: E402
from _model_evolution_reporting import _registered_plan as analysis_plan  # noqa: E402
from _model_evolution_state import StateError, register_plan  # noqa: E402
from model_evolution import _registered_plan as record_plan  # noqa: E402
from writing_plans_verifier import (  # noqa: E402
    DESCRIPTION_VALUE,
    _fixed_case_checks,
)


ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
SKILLS = {
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
}


def run_script(relative: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative), *arguments],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


class ExtendedRelease(unittest.TestCase):
    def test_plan_replacement_is_strict_and_consumable(self) -> None:
        old = {
            "role": "target_current",
            "skill_id": "skill-evaluator",
            "plan": {"root": "campaign", "path": "old/plan.json"},
            "plan_digest": f"sha256:{'1' * 64}",
            "host_id": "host",
            "host_version": "1",
            "execute_ceiling": 72,
            "model_grade_ceiling": 48,
            "runner_status": {"completed": 0, "total": 36, "failed": 0},
        }
        new = {
            **old,
            "plan": {"root": "campaign", "path": "new/plan.json"},
            "plan_digest": f"sha256:{'2' * 64}",
        }
        state = {
            "state_revision": 10,
            "phase": "calibration_ready",
            "plans": [old],
            "candidate": None,
            "profiles": {"predecessor": None},
            "budgets": {
                "ceiling": {"execute": 200, "model_grade": 200,
                            "provider_requests": 400},
                "reserved": {"execute": 72, "model_grade": 48,
                             "provider_requests": 120},
            },
            "skill_evidence": {
                "skill-evaluator": {"grader_calibration": {"root": "campaign"}},
                "writing-plans": {"grader_calibration": {"root": "campaign"}},
            },
        }
        stopped = {
            "active_attempts": [],
            "recoverable_attempts": [],
            "indexed_attempts": 7,
        }
        empty = {
            "active_attempts": [],
            "recoverable_attempts": [],
            "indexed_attempts": 0,
            "completed_entries": 0,
            "invalid_attempts": 0,
        }

        def replace(
            candidate: dict[str, object] = new,
            *,
            old_status: dict[str, object] = stopped,
            new_status: dict[str, object] = empty,
            runner_stopped: bool = True,
        ) -> dict[str, object]:
            target = deepcopy(state)
            register_plan(
                target,
                deepcopy(candidate),
                replace_existing=True,
                old_runner_stopped=runner_stopped,
                old_runner_status=old_status,
                new_runner_status=new_status,
            )
            return target

        rejected = (
            {"runner_stopped": False},
            {"old_status": {**stopped, "active_attempts": ["attempt.1"]}},
            {"old_status": {**stopped, "recoverable_attempts": ["attempt.1"]}},
            {"new_status": {**empty, "indexed_attempts": 1}},
            {"candidate": {**new, "execute_ceiling": 73}},
            {"candidate": {**new, "skill_id": "writing-plans"}},
        )
        for arguments in rejected:
            with self.subTest(arguments=arguments), self.assertRaises(StateError):
                replace(**arguments)

        updated = replace()
        self.assertEqual(state["budgets"]["reserved"], updated["budgets"]["reserved"])
        self.assertEqual([new], updated["plans"])
        self.assertEqual(old["plan_digest"], updated["plan_replacement_lineage"][0]["plan_digest"])
        self.assertEqual(new, record_plan(updated, "target_current", "skill-evaluator"))
        self.assertEqual(new, analysis_plan(updated, "target_current", "skill-evaluator"))

    def test_writing_plans_parsed_description_proof_is_fail_closed(self) -> None:
        proof = f'''Plan `fixtures/agents/openai.yaml` from 8.2.0 to 8.2.1.
```python
from pathlib import Path
lines = Path("fixtures/agents/openai.yaml").read_text().splitlines()
values = dict(line.split(": ", 1) for line in lines)
assert values["version"] == "8.2.1"
assert values["description"] == "{DESCRIPTION_VALUE}"
```
'''

        def passes(answer: str) -> bool:
            checks = _fixed_case_checks("protected-description", answer)
            return all(passed for passed, _ in checks.values())

        self.assertTrue(passes(proof))
        self.assertFalse(passes(proof.replace(DESCRIPTION_VALUE, "EXPECTED_DESCRIPTION")))
        self.assertFalse(passes(
            proof.replace(
                f'assert values["description"] == "{DESCRIPTION_VALUE}"',
                f'correct = "{DESCRIPTION_VALUE}"\nassert values["description"] == "wrong"',
            )
        ))

    def test_apparatus_operation_uses_producer_verdict(self) -> None:
        operation = {
            "operation_id": "fake-candidate-analyze",
            "status": "pass",
            "duration_ms": 1,
            "state_revision": 0,
            "exit_code": 3,
            "diagnostic": None,
        }
        report = {
            "schema_version": "model-evolution-apparatus-report/2",
            "campaign_id": "campaign-test",
            "state_revision": 0,
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "status": "pass",
            "operations": [operation],
        }
        campaign = {
            "campaign_id": report["campaign_id"],
            "state_revision": 0,
            "product": {
                "source_commit": report["source_commit"],
                "source_tree": report["source_tree"],
            },
            "apparatus_report": {
                "root": "campaign",
                "path": "apparatus-report.json",
                "schema_version": "model-evolution-apparatus-report/2",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "apparatus-report.json"

            def validate(candidate: dict[str, object]) -> None:
                report["operations"] = [candidate]
                report_path.write_text(json.dumps(report), encoding="utf-8")
                _apparatus_artifact(campaign, ROOT, root)

            validate(operation)
            for exit_code in (True, "3", -1):
                with self.subTest(exit_code=exit_code):
                    with self.assertRaises(ContractError):
                        validate({**operation, "exit_code": exit_code})
            with self.assertRaises(ContractError):
                validate({**operation, "status": "fail"})

    def test_plugin_build_and_static_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            plugin = work / "frontier-engineering-plugin"
            evidence = work / "build.json"
            built = run_script(
                "scripts/build_codex_plugin.py",
                "--source-root",
                str(ROOT),
                "--output",
                str(plugin),
                "--evidence-output",
                str(evidence),
            )
            self.assertEqual(0, built.returncode, built.stdout + built.stderr)
            self.assertEqual(SKILLS, {path.name for path in (plugin / "skills").iterdir()})

            smoke_path = work / "smoke.json"
            smoked = run_script(
                "scripts/smoke_codex_plugin.py",
                "--plugin-root",
                str(plugin),
                "--build-evidence",
                str(evidence),
                "--output",
                str(smoke_path),
            )
            self.assertEqual(0, smoked.returncode, smoked.stdout + smoked.stderr)
            smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
            self.assertEqual("frontier-engineering/8.0.1", smoke["bundle_id"])
            self.assertFalse(smoke["actual_codex_cli_install"])

    def test_source_archives_are_clean_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            bundle_bytes = []
            for ordinal in range(2):
                archive = work / f"bundle-{ordinal}.zip"
                evidence = work / f"bundle-{ordinal}.json"
                result = run_script(
                    "scripts/build_source_archive.py",
                    "--source-root",
                    str(ROOT),
                    "--output",
                    str(archive),
                    "--evidence-output",
                    str(evidence),
                    "--layout",
                    "bundle",
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                bundle_bytes.append(archive.read_bytes())
                with zipfile.ZipFile(archive) as source:
                    names = source.namelist()
                self.assertTrue(all(name.startswith("frontier-engineering-bundle/") for name in names))
                self.assertFalse(
                    any(
                        part in {".git", ".work", ".worktrees", "reference", "__pycache__"}
                        for name in names
                        for part in Path(name).parts
                    )
                )
            self.assertEqual(bundle_bytes[0], bundle_bytes[1])

            skills_archive = work / "skills.zip"
            skills_evidence = work / "skills.json"
            result = run_script(
                "scripts/build_source_archive.py",
                "--source-root",
                str(ROOT),
                "--output",
                str(skills_archive),
                "--evidence-output",
                str(skills_evidence),
                "--layout",
                "skills_only",
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            with zipfile.ZipFile(skills_archive) as source:
                roots = {Path(name).parts[0] for name in source.namelist()}
            self.assertEqual(SKILLS, roots)


if __name__ == "__main__":
    unittest.main()
