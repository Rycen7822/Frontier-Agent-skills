from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedLifecycleConformance(SkillEvaluatorTestCase):  # noqa: F405
    def _prepare_plan(
        self,
        root: Path,
    ) -> tuple[dict[str, Path], Path, dict, Path]:
        paths = materialize_epoch6_lifecycle_inputs(root)  # noqa: F405
        calibrated = self.run_cmd(
            'scripts/validate_eval_suite.py', 'calibration',
            '--spec', str(paths['spec']),
            '--ratings', str(paths['ratings']),
            '--labels', str(paths['labels']),
            '--output', str(paths['calibration']),
        )
        self.assertEqual(
            0, calibrated.returncode, calibrated.stdout + calibrated.stderr,
        )
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        spec['suite']['calibration'] = {
            'path': paths['calibration'].name,
            'digest': 'sha256:' + hashlib.sha256(  # noqa: F405
                paths['calibration'].read_bytes(),
            ).hexdigest(),
            'schema_version': 'grader-calibration/3',
        }
        paths['spec'].write_text(
            json.dumps(spec, indent=2) + '\n', encoding='utf-8',
        )
        rebind_epoch6_contract_fixture(paths)  # noqa: F405

        quality = self.run_cmd(
            'scripts/validate_eval_suite.py', 'suite-quality',
            '--spec', str(paths['spec']),
            '--proof', str(paths['quality_proof']),
            '--output', str(paths['generated_quality']),
        )
        self.assertEqual(0, quality.returncode, quality.stdout + quality.stderr)
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        spec['suite']['quality'] = {
            'path': paths['generated_quality'].name,
            'digest': 'sha256:' + hashlib.sha256(  # noqa: F405
                paths['generated_quality'].read_bytes(),
            ).hexdigest(),
            'schema_version': 'suite-quality/2',
        }
        spec['execution']['ready'] = True
        paths['spec'].write_text(
            json.dumps(spec, indent=2) + '\n', encoding='utf-8',
        )
        contract = self.run_cmd(
            'scripts/validate_eval_suite.py', 'contract',
            str(paths['spec']), str(paths['scenarios']), str(paths['host']),
        )
        self.assertEqual(0, contract.returncode, contract.stdout + contract.stderr)

        plan_path = root / 'execution-plan.json'
        compiled = self.run_cmd(
            'scripts/compile_eval_plan.py',
            str(paths['spec']), str(paths['scenarios']), str(paths['host']),
            '--output', str(plan_path),
        )
        self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        index_path = (
            root / plan['artifacts']['root']
            / plan['artifacts']['index_relpath']
        )
        return paths, plan_path, plan, index_path

    def _status(
        self,
        plan_path: Path,
        index_path: Path,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = self.run_cmd(
            'scripts/run_eval_plan.py', str(plan_path),
            '--index', str(index_path), '--status',
        )
        return result, json.loads(result.stdout) if result.returncode == 0 else {}

    @staticmethod
    def _wait_for(predicate, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        delay = 0.01
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(delay)
            delay = min(delay * 2, 0.2)
        return predicate()

    def test_public_cli_closes_four_entry_interrupted_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, plan_path, plan, index_path = self._prepare_plan(root)
            entries = sorted(
                (
                    entry for entry in plan['entries']
                    if entry['disposition'] == 'execute'
                ),
                key=lambda entry: entry['entry_ordinal'],
            )
            self.assertEqual(4, len(entries))
            self.assertTrue(all(entry['model_grade_specs'] for entry in entries))
            source_state = {
                name: (path.read_bytes(), path.stat().st_mode & 0o777)
                for name, path in (
                    ('module', paths['workspace_module']),
                    ('tool', paths['workspace_tool']),
                )
            }
            self.assertEqual(0o444, source_state['module'][1])
            self.assertEqual(0o555, source_state['tool'][1])

            initial, initial_status = self._status(plan_path, index_path)
            self.assertEqual(0, initial.returncode, initial.stdout + initial.stderr)
            self.assertEqual(0, initial_status['completed_entries'])
            for completed, entry in enumerate(entries[:3], start=1):
                runner_arguments = [
                    'scripts/run_eval_plan.py', str(plan_path),
                    '--index', str(index_path),
                    '--entry-id', entry['entry_id'],
                    '--new-attempt-budget', '1',
                ]
                if completed > 1:
                    runner_arguments.append('--resume')
                ran = self.run_cmd(*runner_arguments)
                self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
                observed, status = self._status(plan_path, index_path)
                self.assertEqual(
                    0, observed.returncode, observed.stdout + observed.stderr,
                )
                self.assertEqual(completed, status['completed_entries'])
                self.assertEqual(completed, status['indexed_attempts'])

            final_entry = entries[-1]
            attempt_dir = (
                root / plan['artifacts']['root']
                / final_entry['artifact_relpath'] / 'attempt-0001'
            )
            stop_path = (
                attempt_dir / 'graders' / 'fixture-grader' / 'verifier-stopped'
            )
            environment = {
                **os.environ,
                'SKILL_EVALUATOR_STOP_ENTRY_ID': final_entry['entry_id'],
            }
            runner = subprocess.Popen(
                [
                    PYTHON, 'scripts/run_eval_plan.py', str(plan_path),  # noqa: F405
                    '--index', str(index_path),
                    '--entry-id', final_entry['entry_id'],
                    '--new-attempt-budget', '1',
                    '--resume',
                ],
                cwd=ROOT,  # noqa: F405
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            verifier_pid: int | None = None
            try:
                self.assertTrue(
                    self._wait_for(stop_path.is_file),
                    'deterministic verifier did not reach the stop boundary',
                )
                verifier_pid = int(stop_path.read_text(encoding='utf-8'))
                self.assertIsNone(runner.poll())
                self.assertTrue((attempt_dir / 'result.json').is_file())
                _, interrupted_rows = load_run_index(index_path)
                self.assertEqual(3, len(interrupted_rows))
                active_result, active = self._status(plan_path, index_path)
                self.assertEqual(
                    0, active_result.returncode,
                    active_result.stdout + active_result.stderr,
                )
                self.assertEqual(
                    [{'entry_id': final_entry['entry_id'], 'attempt': 1}],
                    active['active_attempts'],
                )
                before_blocked = index_path.read_bytes()
                blocked = self.run_cmd(
                    'scripts/run_eval_plan.py', str(plan_path),
                    '--index', str(index_path), '--resume',
                    '--new-attempt-budget', '0',
                )
                self.assertEqual(2, blocked.returncode)
                self.assertEqual(before_blocked, index_path.read_bytes())

                runner.kill()
                runner.communicate(timeout=5)
                still_active_result, still_active = self._status(
                    plan_path, index_path,
                )
                self.assertEqual(
                    0, still_active_result.returncode,
                    still_active_result.stdout + still_active_result.stderr,
                )
                self.assertEqual(1, len(still_active['active_attempts']))
                os.kill(verifier_pid, signal.SIGCONT)

                recovered: dict = {}

                def lock_released() -> bool:
                    nonlocal recovered
                    result, status = self._status(plan_path, index_path)
                    if result.returncode == 0 and status['recoverable_attempts']:
                        recovered = status
                        return True
                    return False

                self.assertTrue(
                    self._wait_for(lock_released),
                    'child custody did not become recoverable',
                )
                self.assertEqual(
                    [{'entry_id': final_entry['entry_id'], 'attempt': 1}],
                    recovered['recoverable_attempts'],
                )
            finally:
                if runner.poll() is None:
                    runner.kill()
                    runner.communicate(timeout=5)
                if verifier_pid is not None:
                    try:
                        os.kill(verifier_pid, signal.SIGCONT)
                    except ProcessLookupError:
                        pass

            sealed = self.run_cmd(
                'scripts/run_eval_plan.py', str(plan_path),
                '--index', str(index_path), '--resume',
                '--new-attempt-budget', '0',
            )
            self.assertEqual(3, sealed.returncode, sealed.stdout + sealed.stderr)
            _, rows = load_run_index(index_path)
            self.assertEqual(4, len(rows))
            self.assertEqual(4, len({row['entry_id'] for row in rows}))
            self.assertEqual(
                {
                    f"attempt.{entry['entry_ordinal']}.1"
                    for entry in plan['entries']
                },
                {row['attempt_id'] for row in rows},
            )
            self.assertFalse(any(root.rglob('attempt-0002')))

            requests = []
            for row in rows:
                receipt = json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                requests.extend(receipt['host_protocol']['requests'])
                workspace = (
                    root / plan['artifacts']['root'] / row['artifact_dir']
                    / 'workspace'
                )
                self.assertTrue(
                    workspace.joinpath('workspace_module.py').stat().st_mode
                    & 0o200,
                )
                self.assertTrue(
                    workspace.joinpath('workspace_tool.sh').stat().st_mode
                    & 0o100,
                )
            identities = [
                (
                    request['envelope']['run_id'],
                    request['envelope']['request_kind'],
                    request['envelope']['request_id'],
                )
                for request in requests
            ]
            self.assertEqual(len(identities), len(set(identities)))
            self.assertEqual(
                source_state,
                {
                    name: (path.read_bytes(), path.stat().st_mode & 0o777)
                    for name, path in (
                        ('module', paths['workspace_module']),
                        ('tool', paths['workspace_tool']),
                    )
                },
            )
            self.assertFalse(any(root.rglob('__pycache__')))
            if verifier_pid is not None:
                self.assertTrue(self._wait_for(
                    lambda: not Path(f'/proc/{verifier_pid}').exists(),
                ))

            summary_path = root / 'summary.json'
            failure_path = root / 'failures.json'
            arguments = (
                str(index_path), '--spec', str(paths['spec']),
                '--json', str(summary_path),
                '--failure-index', str(failure_path),
            )
            first = self.call_cli('scripts/analyze_runs.py', *arguments)
            self.assertIn(first.returncode, {0, 1, 3})
            first_bytes = (summary_path.read_bytes(), failure_path.read_bytes())
            second = self.call_cli('scripts/analyze_runs.py', *arguments)
            self.assertEqual(first.returncode, second.returncode)
            self.assertEqual(
                first_bytes,
                (summary_path.read_bytes(), failure_path.read_bytes()),
            )


if __name__ == '__main__':
    unittest.main()  # noqa: F405
