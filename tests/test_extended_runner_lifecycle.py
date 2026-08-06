from __future__ import annotations

import time

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedRunnerLifecycle(SkillEvaluatorTestCase):  # noqa: F405
    def _compile(
        self,
        root: Path,
    ) -> tuple[dict[str, Path], Path, dict, dict, Path]:
        paths = materialize_v5_contract_fixture(root)
        return self._compile_from_paths(root, paths)

    @staticmethod
    def _snapshot(root: Path) -> list[tuple[str, str, bytes | None]]:
        snapshot = []
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                snapshot.append((relative, f'link:{os.readlink(path)}', None))
            elif path.is_dir():
                snapshot.append((relative, 'dir', None))
            else:
                snapshot.append((relative, 'file', path.read_bytes()))
        return snapshot

    def _status(
        self,
        plan_path: Path,
        index_path: Path,
        entry_id: str,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cmd(
            'scripts/run_eval_plan.py',
            str(plan_path),
            '--index', str(index_path),
            '--entry-id', entry_id,
            '--status',
            *extra,
        )

    def test_status_is_canonical_read_only_and_tracks_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan_path, plan, entry, index_path = self._compile(root)
            before = self._snapshot(root)
            first = self._status(plan_path, index_path, entry['entry_id'])
            second = self._status(plan_path, index_path, entry['entry_id'])
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertEqual(first.stdout.encode(), second.stdout.encode())
            self.assertEqual(before, self._snapshot(root))
            status = json.loads(first.stdout)
            self.assertEqual(
                {
                    'selected_entries': 1,
                    'execute_entries': 1,
                    'indexed_attempts': 0,
                    'completed_entries': 0,
                    'invalid_attempts': 0,
                    'remaining_entries': 1,
                    'next_pass_new_attempts': 1,
                    'worst_case_remaining_attempts': 1,
                    'execute_case_request_ceiling': 1,
                    'model_grade_request_ceiling': 0,
                },
                {key: status[key] for key in (
                    'selected_entries', 'execute_entries', 'indexed_attempts',
                    'completed_entries', 'invalid_attempts',
                    'remaining_entries', 'next_pass_new_attempts',
                    'worst_case_remaining_attempts',
                    'execute_case_request_ceiling',
                    'model_grade_request_ceiling',
                )},
            )
            validator = load_validator_module()
            self.assertEqual([], validator.validate_v5_schema(
                status,
                'runner-status-v1.schema.json',
                validator.load_v5_schema_registry(),
            ))

            ran = self.run_cmd(
                'scripts/run_eval_plan.py',
                str(plan_path),
                '--index', str(index_path),
                '--entry-id', entry['entry_id'],
                '--new-attempt-budget', '1',
            )
            self.assertEqual(0, ran.returncode, ran.stdout + ran.stderr)
            self.assertIn('RUN PREFLIGHT:', ran.stdout)
            attempt_dir = (
                root / plan['artifacts']['root']
                / entry['artifact_relpath'] / 'attempt-0001'
            )
            self.assertFalse((attempt_dir / 'attempt-custody.lock').exists())
            completed = json.loads(
                self._status(
                    plan_path, index_path, entry['entry_id'],
                ).stdout,
            )
            self.assertEqual(1, completed['indexed_attempts'])
            self.assertEqual(1, completed['completed_entries'])
            self.assertEqual(0, completed['remaining_entries'])
            self.assertIsNone(completed['next_entry_id'])
            self.assertIsNone(completed['next_attempt'])

    def test_budget_preflight_failures_leave_tree_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan_path, _, entry, index_path = self._compile(root)
            base = [
                'scripts/run_eval_plan.py', str(plan_path),
                '--index', str(index_path),
                '--entry-id', entry['entry_id'],
            ]
            before = self._snapshot(root)
            cases = (
                (),
                ('--new-attempt-budget', '-1'),
                ('--new-attempt-budget', '0'),
                ('--new-attempt-budget', '2'),
            )
            for arguments in cases:
                with self.subTest(arguments=arguments):
                    result = self.run_cmd(*base, *arguments)
                    self.assertEqual(
                        2, result.returncode, result.stdout + result.stderr,
                    )
                    self.assertEqual(before, self._snapshot(root))
            conflict = self._status(
                plan_path, index_path, entry['entry_id'],
                '--max-parallel', '1',
            )
            self.assertEqual(2, conflict.returncode)
            self.assertEqual(before, self._snapshot(root))

    def test_status_counts_model_requests_from_frozen_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_model_ready_fixture(root)
            _, plan_path, _, entry, index_path = self._compile_from_paths(
                root, paths,
            )
            result = self._status(
                plan_path, index_path, entry['entry_id'],
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            status = json.loads(result.stdout)
            self.assertEqual(1, status['execute_case_request_ceiling'])
            self.assertEqual(1, status['model_grade_request_ceiling'])

    def test_runner_rejects_noncanonical_missing_evidence(self) -> None:
        runner = load_runner_module()
        output = {
            'overall_pass': False,
            'score': 0,
            'checks': [
                {
                    'check_id': 'quality-check',
                    'pass': False,
                    'evidence': [],
                    'notes': '',
                    'uncertainty': 'none',
                },
            ],
            'missing_evidence': ['missing evidence'],
            'grader_failure': False,
            'grader_failure_reason': None,
        }
        with self.assertRaisesRegex(
            runner.ApparatusFailure,
            'missing_evidence output is invalid',
        ):
            runner._validate_grader_output(output, ['quality-check'])

    def test_spawn_failure_keeps_recoverable_lock_file_without_child(self) -> None:
        runner = load_runner_module()
        with tempfile.TemporaryDirectory() as tmp:
            attempt_dir = Path(tmp) / 'attempt-0001'
            attempt_dir.mkdir()
            with runner._AttemptCustody(attempt_dir) as custody:
                with self.assertRaisesRegex(
                    runner.ApparatusFailure,
                    'child process could not start',
                ):
                    runner._run_process(
                        ['/definitely-missing-skill-evaluator-host'],
                        cwd=attempt_dir,
                        environment={},
                        input_bytes=b'',
                        timeout_seconds=1,
                        custody_fd=custody.fd,
                    )
            self.assertTrue(
                (attempt_dir / runner.ATTEMPT_CUSTODY_NAME).is_file(),
            )
            self.assertFalse(any(
                path.name.startswith('host-') for path in attempt_dir.iterdir()
            ))

    def test_tampered_marker_request_and_symlink_lock_fail_without_cleanup(
        self,
    ) -> None:
        evidence = load_evidence_io_module()
        for mutation in (
            'marker-ownership', 'partial-request', 'request-identity',
            'symlink-lock',
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if mutation == 'symlink-lock':
                    paths, plan_path, plan, entry, index_path = self._compile(root)
                else:
                    paths = materialize_v5_contract_fixture(root)
                    set_v5_synthetic_host_mode(paths, 'host-exit')
                    (
                        paths, plan_path, plan, entry, index_path,
                    ) = self._compile_from_paths(root, paths)
                attempt_dir = (
                    root / plan['artifacts']['root']
                    / entry['artifact_relpath'] / 'attempt-0001'
                )
                if mutation == 'symlink-lock':
                    attempt_dir.mkdir(parents=True)
                    outside = root / 'outside-lock'
                    outside.write_text('outside', encoding='utf-8')
                    (attempt_dir / 'attempt-custody.lock').symlink_to(outside)
                else:
                    first = self.run_cmd(
                        'scripts/run_eval_plan.py', str(plan_path),
                        '--index', str(index_path),
                        '--entry-id', entry['entry_id'],
                        '--new-attempt-budget', '1',
                    )
                    self.assertEqual(
                        3, first.returncode, first.stdout + first.stderr,
                    )
                    if mutation == 'marker-ownership':
                        marker_path = attempt_dir / 'attempt-start.json'
                        marker = json.loads(
                            marker_path.read_text(encoding='utf-8'),
                        )
                        marker['ownership_token'] = 'sha256:' + '0' * 64
                        marker['marker_hash'] = evidence.canonical_self_hash(
                            marker, 'marker_hash',
                        )
                        marker_path.write_bytes(
                            evidence.canonical_json_bytes(marker) + b'\n',
                        )
                    elif mutation == 'partial-request':
                        (attempt_dir / 'host-request.json').write_bytes(b'{')
                    else:
                        request_path = attempt_dir / 'host-request.json'
                        request = json.loads(
                            request_path.read_text(encoding='utf-8'),
                        )
                        request['envelope']['run_id'] = 'run-' + '0' * 24
                        request['request_hash'] = evidence.canonical_self_hash(
                            request, 'request_hash',
                        )
                        request_path.write_bytes(
                            evidence.canonical_json_bytes(request) + b'\n',
                        )
                before = self._snapshot(root)
                status = self._status(
                    plan_path, index_path, entry['entry_id'],
                )
                self.assertEqual(2, status.returncode)
                resumed = self.run_cmd(
                    'scripts/run_eval_plan.py', str(plan_path),
                    '--index', str(index_path),
                    '--entry-id', entry['entry_id'],
                    '--resume', '--new-attempt-budget', '0',
                )
                self.assertEqual(2, resumed.returncode)
                self.assertEqual(before, self._snapshot(root))

    def test_child_inherits_custody_after_parent_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan_path, plan, entry, index_path = self._compile(root)
            attempt_dir = (
                root / plan['artifacts']['root']
                / entry['artifact_relpath'] / 'attempt-0001'
            )
            attempt_dir.mkdir(parents=True)
            done_path = root / 'child-done'
            child_code = (
                'import os,sys; from pathlib import Path; os.read(0,1); '
                'Path(sys.argv[1]).write_text("done")'
            )
            owner_code = (
                'import os,subprocess,sys\n'
                'from pathlib import Path\n'
                f'sys.path.insert(0,{str(ROOT / "scripts")!r})\n'
                'import run_eval_plan as runner\n'
                'attempt=Path(sys.argv[1]); done=Path(sys.argv[2])\n'
                'with runner._AttemptCustody(attempt) as custody:\n'
                f' child=subprocess.Popen([sys.executable,"-c",{child_code!r},str(done)],'
                'stdin=None,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,'
                'pass_fds=(custody.fd,))\n'
                ' print(child.pid,flush=True)\n'
                ' os._exit(0)\n'
            )
            owner = subprocess.Popen(
                [sys.executable, '-c', owner_code, str(attempt_dir), str(done_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )
            owner.wait(timeout=5)
            owner_output = owner.stdout.read().decode().strip()
            owner_error = owner.stderr.read().decode()
            self.assertEqual(0, owner.returncode, owner_error)
            child_pid = int(owner_output)
            active = self._status(plan_path, index_path, entry['entry_id'])
            self.assertEqual(0, active.returncode, active.stdout + active.stderr)
            self.assertEqual(
                [{'entry_id': entry['entry_id'], 'attempt': 1}],
                json.loads(active.stdout)['active_attempts'],
            )
            before = self._snapshot(attempt_dir)
            blocked = self.run_cmd(
                'scripts/run_eval_plan.py', str(plan_path),
                '--index', str(index_path),
                '--entry-id', entry['entry_id'],
                '--resume', '--new-attempt-budget', '0',
            )
            self.assertEqual(2, blocked.returncode)
            self.assertIn('attempt is still active', blocked.stderr)
            self.assertEqual(before, self._snapshot(attempt_dir))

            owner.stdin.write(b'x')
            owner.stdin.close()
            deadline = time.monotonic() + 5
            while not done_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(done_path.is_file())
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.01)
            else:
                self.fail('custody child did not exit')

    def test_budget_zero_seals_but_does_not_create_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            set_v5_synthetic_host_mode(paths, 'transient-first-attempt')
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['execution']['retry_policy'] = {
                'max_attempts': 2,
                'retryable_apparatus_classes': ['official_transient'],
                'backoff_seconds': 0,
            }
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            _, plan_path, plan, entry, index_path = self._compile_from_paths(
                root, paths,
            )
            first = self.run_cmd(
                'scripts/run_eval_plan.py', str(plan_path),
                '--index', str(index_path),
                '--new-attempt-budget', '2',
            )
            self.assertEqual(3, first.returncode, first.stdout + first.stderr)
            recoverable = json.loads(self.run_cmd(
                'scripts/run_eval_plan.py', str(plan_path),
                '--index', str(index_path), '--status',
            ).stdout)
            self.assertEqual(0, recoverable['next_pass_new_attempts'])
            resumed = self.run_cmd(
                'scripts/run_eval_plan.py', str(plan_path),
                '--index', str(index_path),
                '--resume', '--new-attempt-budget', '0',
            )
            self.assertEqual(3, resumed.returncode)
            self.assertIn('new-attempt budget exhausted', resumed.stderr)
            rows = [
                json.loads(line)
                for line in index_path.read_text(encoding='utf-8').splitlines()
            ]
            self.assertEqual([1], [row['attempt'] for row in rows])
            self.assertFalse((
                root / plan['artifacts']['root']
                / entry['artifact_relpath'] / 'attempt-0002'
            ).exists())
            later_entry = next(
                item for item in plan['entries']
                if item['disposition'] == 'execute'
                and item['entry_id'] != entry['entry_id']
            )
            self.assertFalse((
                root / plan['artifacts']['root']
                / later_entry['artifact_relpath'] / 'attempt-0001'
            ).exists())

    def _compile_from_paths(
        self,
        root: Path,
        paths: dict[str, Path],
    ) -> tuple[dict[str, Path], Path, dict, dict, Path]:
        plan_path = root / 'execution-plan.json'
        result = self.run_cmd(
            'scripts/compile_eval_plan.py',
            str(paths['spec']), str(paths['scenarios']), str(paths['host']),
            '--output', str(plan_path),
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        entry = next(
            item for item in plan['entries']
            if item['disposition'] == 'execute'
        )
        index_path = (
            root / plan['artifacts']['root']
            / plan['artifacts']['index_relpath']
        )
        return paths, plan_path, plan, entry, index_path
