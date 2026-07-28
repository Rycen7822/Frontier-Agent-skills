from __future__ import annotations

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedEvalExecution(SkillEvaluatorTestCase):  # noqa: F405
    def _run_compiler(
        self,
        paths: dict[str, Path],
        output: Path,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cmd(
            'scripts/compile_eval_plan.py',
            str(paths['spec']),
            str(paths['scenarios']),
            str(paths['host']),
            '--output', str(output),
        )

    def _compile_fixture(
        self,
        root: Path,
        *,
        output_name: str = 'execution-plan.json',
    ) -> tuple[dict[str, Path], dict]:
        paths = materialize_v5_contract_fixture(root)
        output = root / output_name
        result = self._run_compiler(paths, output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return paths, json.loads(output.read_text(encoding='utf-8'))

    def _run_runner(
        self,
        plan_path: Path,
        index_path: Path,
        *args: str,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cmd(
            'scripts/run_eval_plan.py',
            str(plan_path),
            '--index', str(index_path),
            *args,
            env=environment,
        )

    def test_runner_executes_compiled_entries_into_receipts_and_index(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan = self._compile_fixture(root)
            plan_path = root / 'execution-plan.json'
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            result = self._run_runner(plan_path, index_path)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = [
                json.loads(line)
                for line in index_path.read_text(encoding='utf-8').splitlines()
            ]
            self.assertEqual(plan['expected_counts']['execute'], len(rows))
            for entry, row in zip(plan['entries'], rows, strict=True):
                self.assertEqual(2, row['schema_version'])
                self.assertEqual(entry['entry_id'], row['entry_id'])
                self.assertEqual(entry['entry_ordinal'], row['entry_ordinal'])
                self.assertEqual(1, row['attempt'])
                self.assertEqual(
                    {
                        'schema_version', 'plan_hash', 'plan_id',
                        'entry_ordinal', 'entry_id', 'run_id', 'case_id',
                        'treatment_id', 'repeat', 'attempt', 'artifact_dir',
                        'receipt',
                    },
                    set(row),
                )
                receipt_path = root / plan['artifacts']['root'] / row[
                    'receipt'
                ]['path']
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                self.assertEqual(4, receipt['schema_version'])
                self.assertTrue(
                    load_evidence_io_module().verify_self_hash(
                        receipt, 'receipt_hash',
                    ),
                )
                self.assertEqual(entry['entry_id'], receipt['run']['entry_id'])

    def test_runner_closes_state_principal_and_handoff_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_handoff_fixture(root)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            handoff_id = (
                'handoff-'
                + canonical_hash({'from': 'lead', 'to': 'worker'}).removeprefix(
                    'sha256:',
                )
            )
            self.assertTrue(all(
                entry['handoff_ids'] == [handoff_id]
                for entry in plan['entries']
            ))
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            run_result = self._run_runner(plan_path, index_path)
            self.assertEqual(
                run_result.returncode, 0,
                run_result.stdout + run_result.stderr,
            )
            for row in map(
                json.loads,
                index_path.read_text(encoding='utf-8').splitlines(),
            ):
                receipt = json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                self.assertEqual(
                    {'lead', 'worker'},
                    {item['slot_id'] for item in receipt['principals']},
                )
                self.assertEqual(
                    [handoff_id],
                    [item['handoff_id'] for item in receipt['handoffs']],
                )
                self.assertEqual(2, len(receipt['state']['checkpoints']))

    def test_runner_closes_exact_routing_and_composition_contracts(self) -> None:
        for materialize in (
            materialize_v5_routing_fixture,
            materialize_v5_composition_fixture,
        ):
            with (
                self.subTest(materialize=materialize.__name__),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                paths = materialize(root)
                plan_path = root / 'execution-plan.json'
                compiled = self._run_compiler(paths, plan_path)
                self.assertEqual(
                    compiled.returncode, 0,
                    compiled.stdout + compiled.stderr,
                )
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                index_path = (
                    root / plan['artifacts']['root']
                    / plan['artifacts']['index_relpath']
                )
                executed = self._run_runner(plan_path, index_path)
                self.assertEqual(
                    executed.returncode, 0,
                    executed.stdout + executed.stderr,
                )
                entries = {
                    item['entry_id']: item for item in plan['entries']
                }
                for row in map(
                    json.loads,
                    index_path.read_text(encoding='utf-8').splitlines(),
                ):
                    entry = entries[row['entry_id']]
                    receipt = json.loads(
                        (
                            root / plan['artifacts']['root']
                            / row['receipt']['path']
                        ).read_text(encoding='utf-8'),
                    )
                    contract = entry['execute_case_payload']['case'][
                        'routing_contract'
                    ]
                    profile = entry['execute_case_payload']['treatment'][
                        'profile'
                    ]
                    expected = {
                        item['turn_id']: {
                            key: item[key]
                            for key in (
                                'declared', 'discovered', 'loaded',
                                'model_visible', 'selected', 'invoked',
                                'applied', 'order', 'composition',
                            )
                        }
                        for item in contract['expectations']
                        if item['treatment_profile'] == profile
                    }
                    observed = {
                        item['turn_id']: item['payload']['routing']
                        for item in receipt['host_protocol']['events']
                    }
                    self.assertEqual(expected, observed)
                    self.assertGreater(
                        receipt['context_usage']['controlled_core_bytes'], 0,
                    )
                    self.assertIn(
                        'effective-catalog',
                        {
                            item['component_id']
                            for item in receipt['context_usage']['components']
                        },
                    )

    def test_runner_rejects_routing_evidence_outside_declared_contract(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_routing_fixture(root)
            set_v5_synthetic_host_mode(paths, 'routing-mismatch')
            plan_path = root / 'execution-plan.json'
            compiled = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compiled.returncode, 0, compiled.stdout + compiled.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = (
                root / plan['artifacts']['root']
                / plan['artifacts']['index_relpath']
            )
            result = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                result.returncode, 2, result.stdout + result.stderr,
            )
            self.assertIn(
                'host routing differs from the declared',
                result.stdout + result.stderr,
            )
            self.assertFalse(index_path.exists())

    def test_runner_closes_authorized_action_and_confirmed_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_action_fixture(root)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            action_id = (
                'action-'
                + canonical_hash({'tool_id': 'fixture-tool'}).removeprefix(
                    'sha256:',
                )
            )
            required = {
                'action_authorization_trace',
                'render_effect_capture',
                'tool_schema_model_visible_capture',
            }
            self.assertTrue(all(
                entry['action_ids'] == [action_id]
                and required <= set(entry['required_capabilities'])
                for entry in plan['entries']
            ))
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            run_result = self._run_runner(plan_path, index_path)
            self.assertEqual(
                run_result.returncode, 0,
                run_result.stdout + run_result.stderr,
            )
            for row in map(
                json.loads,
                index_path.read_text(encoding='utf-8').splitlines(),
            ):
                receipt = json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                self.assertEqual([action_id], [
                    action['action_id'] for action in receipt['actions']
                ])
                action = receipt['actions'][0]
                self.assertEqual('allow', action['resolved_decision'])
                self.assertIsNotNone(action['executed_input'])
                self.assertIsNotNone(action['confirmed_effect'])
                self.assertEqual(
                    'effect_confirmed',
                    action['stages'][-1]['stage'],
                )

    def test_action_changes_denial_and_unauthorized_execution_fail_closed(
        self,
    ) -> None:
        for mode, expected_exit in (
            ('allow-with-changes', 0),
            ('deny', 0),
            ('approval-mismatch', 2),
            ('unauthorized-execution', 2),
            ('action-principal-mismatch', 2),
            ('action-tool-mismatch', 2),
            ('action-stage-artifact-mismatch', 2),
            ('authorization-resolution-mismatch', 2),
            ('deny-hidden-execution', 2),
            ('duplicate-action', 2),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = materialize_v5_action_fixture(root)
                set_v5_synthetic_host_mode(paths, mode)
                plan_path = root / 'execution-plan.json'
                compile_result = self._run_compiler(paths, plan_path)
                self.assertEqual(
                    compile_result.returncode, 0,
                    compile_result.stdout + compile_result.stderr,
                )
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                index_path = (
                    root / plan['artifacts']['root']
                    / plan['artifacts']['index_relpath']
                )

                run_result = self._run_runner(
                    plan_path, index_path, '--entry-id',
                    plan['entries'][0]['entry_id'],
                )
                self.assertEqual(
                    expected_exit, run_result.returncode,
                    run_result.stdout + run_result.stderr,
                )
                if expected_exit != 0:
                    self.assertFalse(index_path.exists())
                    continue
                row = json.loads(
                    index_path.read_text(encoding='utf-8').strip(),
                )
                receipt = json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                action = receipt['actions'][0]
                if mode == 'allow-with-changes':
                    self.assertNotEqual(
                        action['proposed_input'], action['executed_input'],
                    )
                    self.assertIsNotNone(action['confirmed_effect'])
                else:
                    self.assertEqual('deny', action['resolved_decision'])
                    self.assertIsNone(action['executed_input'])
                    self.assertIsNone(action['confirmed_effect'])
                    self.assertEqual(
                        'authorization_resolved',
                        action['stages'][-1]['stage'],
                    )

    def test_runner_exit_taxonomy_and_protocol_mutations(self) -> None:
        for mode, expected_exit in (
            ('treatment-failure', 0),
            ('host-exit', 3),
            ('sequence-gap', 2),
            ('duplicate-terminal', 2),
            ('identity-mismatch', 2),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = materialize_v5_contract_fixture(root)
                set_v5_synthetic_host_mode(paths, mode)
                plan_path = root / 'execution-plan.json'
                compile_result = self._run_compiler(paths, plan_path)
                self.assertEqual(
                    compile_result.returncode, 0,
                    compile_result.stdout + compile_result.stderr,
                )
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                entry = plan['entries'][0]
                index_path = (
                    root / plan['artifacts']['root']
                    / plan['artifacts']['index_relpath']
                )

                run_result = self._run_runner(
                    plan_path, index_path, '--entry-id', entry['entry_id'],
                )
                self.assertEqual(
                    expected_exit, run_result.returncode,
                    run_result.stdout + run_result.stderr,
                )
                attempt_dir = (
                    root / plan['artifacts']['root']
                    / entry['artifact_relpath'] / 'attempt-0001'
                )
                self.assertTrue(
                    (attempt_dir / 'attempt-start.json').is_file(),
                )
                if expected_exit == 0:
                    row = json.loads(
                        index_path.read_text(encoding='utf-8').strip(),
                    )
                    receipt = json.loads(
                        (
                            root / plan['artifacts']['root']
                            / row['receipt']['path']
                        ).read_text(encoding='utf-8'),
                    )
                    self.assertTrue(receipt['run']['valid'])
                    self.assertEqual('failed', receipt['run']['terminal'])
                    self.assertEqual(
                        'synthetic treatment failure',
                        receipt['run']['error'],
                    )
                else:
                    self.assertFalse((attempt_dir / 'receipt.json').exists())
                    self.assertFalse(index_path.exists())

    def test_non_execute_selection_has_zero_runtime_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            host['capabilities'][0]['probe']['status'] = 'unsupported'
            host['command']['argv'].append('--mode=host-exit')
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            self.assertTrue(all(
                entry['disposition'] == 'unsupported'
                for entry in plan['entries']
            ))
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            run_result = self._run_runner(
                plan_path, index_path, '--entry-id',
                plan['entries'][0]['entry_id'],
            )
            self.assertEqual(
                run_result.returncode, 0,
                run_result.stdout + run_result.stderr,
            )
            self.assertFalse(
                (root / plan['artifacts']['root']).exists(),
            )

    def test_model_grader_uses_only_blinded_host_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_model_ready_fixture(root)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = next(
                item for item in plan['entries']
                if item['model_grade_specs'][0][
                    'batch_owner_entry_id'
                ] == item['entry_id']
            )
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            run_result = self._run_runner(plan_path, index_path)
            self.assertEqual(
                run_result.returncode, 0,
                run_result.stdout + run_result.stderr,
            )
            rows = [
                json.loads(line)
                for line in index_path.read_text(encoding='utf-8').splitlines()
            ]
            row = next(
                item for item in rows if item['entry_id'] == entry['entry_id']
            )
            receipt = json.loads(
                (
                    root / plan['artifacts']['root']
                    / row['receipt']['path']
                ).read_text(encoding='utf-8'),
            )
            self.assertEqual(1, sum(
                request['envelope']['request_kind'] == 'model_grade'
                for indexed in rows
                for request in json.loads(
                    (
                        root / plan['artifacts']['root']
                        / indexed['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )['host_protocol']['requests']
            ))
            self.assertEqual(
                ['probe_capability', 'execute_case', 'model_grade'],
                [
                    request['envelope']['request_kind']
                    for request in receipt['host_protocol']['requests']
                ],
            )
            self.assertEqual(
                ['model'],
                [output['kind'] for output in receipt['grader_outputs']],
            )
            blinded_record = receipt['grader_outputs'][0]['blinded_input']
            blinded = json.loads(
                (
                    root / plan['artifacts']['root']
                    / row['artifact_dir'] / blinded_record['path']
                ).read_text(encoding='utf-8'),
            )
            serialized = json.dumps(blinded, sort_keys=True)
            self.assertNotIn('treatment_id', serialized)
            self.assertNotIn('causal_role', serialized)
            self.assertNotIn('profile', serialized)
            batch = receipt['host_protocol']['requests'][-1]['payload'][
                'blinded_input'
            ]
            model_spec = entry['model_grade_specs'][0]
            self.assertEqual(model_spec['batch_id'], batch['batch_id'])
            self.assertEqual(model_spec['batch_entry_ids'], [
                item['item_id'] for item in batch['items']
            ])
            self.assertEqual(batch, blinded)
            self.assertTrue(all(
                {
                    'captured_output',
                    'context_evidence',
                    'deterministic_claims',
                    'final_answer',
                    'host_assessment',
                    'task_evidence',
                }
                == set(item['grader_view'])
                for item in batch['items']
            ))
            self.assertTrue(all(
                item['grader_view']['task_evidence']['request_text']
                for item in batch['items']
            ))
            for item in batch['items']:
                view = item['grader_view']
                self.assertTrue(view['deterministic_claims'])
                self.assertEqual(
                    {
                        'body_load_count',
                        'controlled_bytes',
                        'controlled_core_bytes',
                        'reference_load_count',
                        'total_bytes',
                        'unique_reference_bytes',
                    },
                    set(view['context_evidence']),
                )
                self.assertNotIn('(</', view['final_answer'])
            self.assertNotIn('treatment_id', json.dumps(batch, sort_keys=True))
            self.assertEqual(
                ['execute', 'model_grade'],
                [
                    record['phase']
                    for record in receipt['usage']['records']
                ],
            )
            self.assertEqual(
                18,
                sum(
                    record['input_tokens']
                    for record in receipt['usage']['records']
                ),
            )
            self.assertEqual(
                {
                    'capture_status': 'missing',
                    'host_safety_review_count': 1,
                    'host_safety_review_latency_ms': 9.0,
                },
                receipt['usage']['host_safety_review'],
            )
            summary_path = root / 'summary.json'
            failures_path = root / 'failures.json'
            analyze_result = self.run_cmd(
                'scripts/analyze_runs.py',
                str(index_path),
                '--spec', str(paths['spec']),
                '--json', str(summary_path),
                '--failure-index', str(failures_path),
            )
            self.assertEqual(
                analyze_result.returncode,
                3,
                analyze_result.stdout + analyze_result.stderr,
            )
            self.assertEqual(
                'complete',
                json.loads(summary_path.read_text(encoding='utf-8'))[
                    'evidence_status'
                ],
            )

    def test_blinded_grader_evidence_is_bounded_and_fail_closed(self) -> None:
        transport = load_analyzer_module().model_transport
        assessment = {'changed_paths': ['fixtures/app.py']}
        self.assertEqual(
            '[app](<fixtures/app.py>)',
            transport._redact_workspace_paths(  # noqa: SLF001
                '[app](</private/workspace/fixtures/app.py>)',
                assessment,
            ),
        )
        self.assertEqual(
            '[app]( fixtures/app.py)',
            transport._redact_workspace_paths(  # noqa: SLF001
                '[app]( /home/example/workspace/fixtures/app.py)',
                assessment,
            ),
        )
        with self.assertRaises(ValueError):
            transport._redact_workspace_paths(  # noqa: SLF001
                '[other](</private/workspace/fixtures/other.py>)',
                assessment,
            )
        with self.assertRaises(ValueError):
            transport._task_evidence({})  # noqa: SLF001
        with self.assertRaises(ValueError):
            transport._deterministic_claims({  # noqa: SLF001
                'artifacts': [],
                'assertions': [],
            })
        with self.assertRaises(ValueError):
            transport._context_evidence({})  # noqa: SLF001

    def test_model_grader_batch_rejects_incomplete_or_mismatched_output(
        self,
    ) -> None:
        transport = load_analyzer_module().model_transport
        batch = transport.execution_batch(
            [{
                'item_id': entry_id,
                'checks': [{'id': 'outcome-check'}],
                'grader_view': {
                    'captured_output': {},
                    'host_assessment': {},
                    'final_answer': 'done',
                },
            } for entry_id in ('entry-a', 'entry-b')],
            batch_id='batch-fixture',
        )

        def judgment(entry_id: str, check_id: str = 'outcome-check') -> dict:
            return {
                'item_id': entry_id,
                'checks': [{
                    'id': check_id,
                    'pass': True,
                    'notes': 'verified',
                    'uncertainty': 'none',
                }],
            }

        output = {
            'batch_id': 'batch-fixture',
            'items': [judgment('entry-b'), judgment('entry-a')],
        }
        normalized, pointers = transport.normalize_judgment(
            output,
            batch=batch,
            requirements=[{'check_id': 'outcome-check', 'required': True}],
            item_id='entry-b',
        )
        self.assertTrue(normalized['overall_pass'])
        self.assertEqual(
            '/items/0/checks/0/pass',
            pointers['outcome-check'],
        )

        invalid_items = (
            [judgment('entry-a')],
            [judgment('entry-a'), judgment('entry-a')],
            [judgment('entry-a', 'wrong-check'), judgment('entry-b')],
        )
        for items in invalid_items:
            with self.subTest(items=items):
                with self.assertRaisesRegex(
                    ValueError,
                    'judgment differs from the bound batch',
                ):
                    transport.normalize_judgment(
                        {'batch_id': 'batch-fixture', 'items': items},
                        batch=batch,
                        requirements=[{
                            'check_id': 'outcome-check',
                            'required': True,
                        }],
                        item_id='entry-a',
                    )

    def test_non_execute_model_entry_emits_no_model_grade_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_model_ready_fixture(root)
            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            next(
                item for item in host['capabilities']
                if item['capability'] == 'model_grading'
            )['probe']['status'] = 'unsupported'
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            self.assertEqual('unsupported', entry['disposition'])
            self.assertTrue(entry['model_grade_specs'])
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            run_result = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                run_result.returncode, 0,
                run_result.stdout + run_result.stderr,
            )
            self.assertFalse(
                (root / plan['artifacts']['root']).exists(),
            )

    def test_runner_rejects_expired_model_calibration_at_attempt_time(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_model_ready_fixture(root)
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            for rating in ratings:
                rating['expires'] = '2026-06-01T00:00:00Z'
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(rating, separators=(',', ':')) + '\n'
                    for rating in ratings
                ),
                encoding='utf-8',
            )
            paths['calibration'].unlink()
            calibration_result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            self.assertEqual(
                calibration_result.returncode, 0,
                calibration_result.stdout + calibration_result.stderr,
            )
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['suite']['calibration']['sha256'] = (
                'sha256:' + hashlib.sha256(
                    paths['calibration'].read_bytes(),
                ).hexdigest()
            )
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            run_result = self._run_runner(
                plan_path, index_path, '--entry-id',
                plan['entries'][0]['entry_id'],
            )
            self.assertEqual(
                run_result.returncode, 3,
                run_result.stdout + run_result.stderr,
            )
            self.assertFalse(
                (root / plan['artifacts']['root']).exists(),
            )

    def test_runner_captures_observation_and_fault_lifecycles(self) -> None:
        for materialize, expected_kind in (
            (materialize_v5_observation_fixture, 'observation'),
            (materialize_v5_fault_fixture, 'fault'),
        ):
            with (
                self.subTest(kind=expected_kind),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                paths = materialize(root)
                plan_path = root / 'execution-plan.json'
                compile_result = self._run_compiler(paths, plan_path)
                self.assertEqual(
                    compile_result.returncode, 0,
                    compile_result.stdout + compile_result.stderr,
                )
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                entry = plan['entries'][0]
                index_path = (
                    root / plan['artifacts']['root']
                    / plan['artifacts']['index_relpath']
                )
                run_result = self._run_runner(
                    plan_path, index_path, '--entry-id', entry['entry_id'],
                )
                self.assertEqual(
                    run_result.returncode, 0,
                    run_result.stdout + run_result.stderr,
                )
                row = json.loads(
                    index_path.read_text(encoding='utf-8').strip(),
                )
                receipt = json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                if expected_kind == 'observation':
                    self.assertEqual(
                        ['source-observation'],
                        [
                            item['observation_id']
                            for item in receipt['observations']
                        ],
                    )
                    self.assertEqual(
                        'pass', receipt['observations'][0]['integrity'],
                    )
                    self.assertEqual(
                        'pass',
                        receipt['observations'][0]['temporal_validity'],
                    )
                else:
                    for phase in ('injected', 'observed', 'recovered'):
                        self.assertEqual(
                            ['fault-timeout'],
                            [
                                item['fault_id']
                                for item in receipt['faults'][phase]
                            ],
                        )

    def test_missing_fault_and_tampered_observation_are_apparatus_failures(
        self,
    ) -> None:
        cases = (
            (
                materialize_v5_observation_fixture,
                'observation-mismatch',
            ),
            (materialize_v5_fault_fixture, 'fault-not-triggered'),
        )
        for materialize, mode in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = materialize(root)
                set_v5_synthetic_host_mode(paths, mode)
                plan_path = root / 'execution-plan.json'
                compile_result = self._run_compiler(paths, plan_path)
                self.assertEqual(
                    compile_result.returncode, 0,
                    compile_result.stdout + compile_result.stderr,
                )
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                entry = plan['entries'][0]
                index_path = (
                    root / plan['artifacts']['root']
                    / plan['artifacts']['index_relpath']
                )

                run_result = self._run_runner(
                    plan_path, index_path, '--entry-id', entry['entry_id'],
                )
                self.assertEqual(
                    run_result.returncode, 3,
                    run_result.stdout + run_result.stderr,
                )
                self.assertFalse(index_path.exists())

    def test_resume_seals_marker_only_attempt_without_inventing_outcome(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            set_v5_synthetic_host_mode(paths, 'host-exit')
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]
            first = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(3, first.returncode, first.stdout + first.stderr)

            resumed = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                resumed.returncode, 3, resumed.stdout + resumed.stderr,
            )
            row = json.loads(index_path.read_text(encoding='utf-8').strip())
            receipt = json.loads(
                (
                    root / plan['artifacts']['root']
                    / row['receipt']['path']
                ).read_text(encoding='utf-8'),
            )
            self.assertEqual(
                'resume_seal', receipt['run']['completion_origin'],
            )
            self.assertFalse(receipt['run']['valid'])
            self.assertEqual('interrupted', receipt['run']['terminal'])
            self.assertEqual([], receipt['host_protocol']['results'])
            self.assertEqual([], receipt['grader_outputs'])
            self.assertFalse(
                (
                    root / plan['artifacts']['root']
                    / entry['artifact_relpath'] / 'attempt-0002'
                ).exists(),
            )

    def test_resume_rejects_no_marker_and_repairs_receipt_index_gap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, plan = self._compile_fixture(root)
            plan_path = root / 'execution-plan.json'
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]
            attempt_dir = (
                root / plan['artifacts']['root']
                / entry['artifact_relpath'] / 'attempt-0001'
            )
            attempt_dir.mkdir(parents=True)
            invalid = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                invalid.returncode, 2, invalid.stdout + invalid.stderr,
            )
            self.assertTrue(attempt_dir.is_dir())
            self.assertFalse(index_path.exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan = self._compile_fixture(root)
            plan_path = root / 'execution-plan.json'
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]
            initial = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                initial.returncode, 0, initial.stdout + initial.stderr,
            )
            expected_index = index_path.read_bytes()
            index_path.unlink()

            repaired = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                repaired.returncode, 0, repaired.stdout + repaired.stderr,
            )
            self.assertEqual(expected_index, index_path.read_bytes())
            completed = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                completed.returncode, 0,
                completed.stdout + completed.stderr,
            )
            self.assertEqual(expected_index, index_path.read_bytes())
            self.assertFalse(
                (
                    root / plan['artifacts']['root']
                    / entry['artifact_relpath'] / 'attempt-0002'
                ).exists(),
            )

    def test_resume_rejects_tampered_index_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan = self._compile_fixture(root)
            plan_path = root / 'execution-plan.json'
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]
            initial = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                initial.returncode, 0, initial.stdout + initial.stderr,
            )
            row = json.loads(index_path.read_text(encoding='utf-8'))
            row['receipt']['sha256'] = 'sha256:' + '0' * 64
            index_path.write_text(
                json.dumps(row, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            tampered = index_path.read_bytes()

            resumed = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                resumed.returncode, 2, resumed.stdout + resumed.stderr,
            )
            self.assertEqual(tampered, index_path.read_bytes())

    def test_retry_retains_invalid_attempt_before_valid_terminal_attempt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            set_v5_synthetic_host_mode(paths, 'fail-first-attempt')
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['execution']['retry_policy'] = {
                'max_attempts': 2,
                'retryable_apparatus_classes': ['interrupted'],
                'backoff_seconds': 0,
            }
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            first = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(3, first.returncode, first.stdout + first.stderr)
            resumed = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                resumed.returncode, 0, resumed.stdout + resumed.stderr,
            )
            rows = [
                json.loads(line)
                for line in index_path.read_text(encoding='utf-8').splitlines()
            ]
            self.assertEqual([1, 2], [row['attempt'] for row in rows])
            receipts = [
                json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                for row in rows
            ]
            self.assertEqual(
                [('resume_seal', False), ('normal', True)],
                [
                    (
                        receipt['run']['completion_origin'],
                        receipt['run']['valid'],
                    )
                    for receipt in receipts
                ],
            )
            stable = index_path.read_bytes()
            repeated = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                repeated.returncode, 0,
                repeated.stdout + repeated.stderr,
            )
            self.assertEqual(stable, index_path.read_bytes())
            self.assertFalse(
                (
                    root / plan['artifacts']['root']
                    / entry['artifact_relpath'] / 'attempt-0003'
                ).exists(),
            )

    def test_timeout_cancel_and_process_timeout_cleanup(self) -> None:
        for mode, terminal in (
            ('treatment-timeout', 'timeout'),
            ('treatment-cancel', 'cancelled'),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = materialize_v5_contract_fixture(root)
                set_v5_synthetic_host_mode(paths, mode)
                plan_path = root / 'execution-plan.json'
                compile_result = self._run_compiler(paths, plan_path)
                self.assertEqual(
                    compile_result.returncode, 0,
                    compile_result.stdout + compile_result.stderr,
                )
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                entry = plan['entries'][0]
                index_path = (
                    root / plan['artifacts']['root']
                    / plan['artifacts']['index_relpath']
                )
                run_result = self._run_runner(
                    plan_path, index_path, '--entry-id', entry['entry_id'],
                )
                self.assertEqual(
                    run_result.returncode, 0,
                    run_result.stdout + run_result.stderr,
                )
                row = json.loads(
                    index_path.read_text(encoding='utf-8').strip(),
                )
                receipt = json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                self.assertTrue(receipt['run']['valid'])
                self.assertEqual(terminal, receipt['run']['terminal'])
                self.assertEqual('clean', receipt['cleanup']['process'])
                self.assertEqual([], receipt['cleanup']['residue'])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            set_v5_synthetic_host_mode(paths, 'host-model-timeout')
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = (
                root / plan['artifacts']['root']
                / plan['artifacts']['index_relpath']
            )
            stopped = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                stopped.returncode, 3,
                stopped.stdout + stopped.stderr,
            )
            self.assertIn('model_task_timeout', stopped.stderr)
            attempt_dir = (
                root / plan['artifacts']['root']
                / entry['artifact_relpath'] / 'attempt-0001'
            )
            result = json.loads(
                (attempt_dir / 'host-stdout.jsonl').read_text(
                    encoding='utf-8',
                ).splitlines()[-1],
            )
            self.assertEqual(
                'model_task_timeout',
                result['failure_class'],
            )
            self.assertEqual(
                'captured',
                result['usage']['host_safety_review']['capture_status'],
            )
            self.assertFalse(index_path.exists())
            self.assertFalse((attempt_dir / 'graders').exists())
            self.assertFalse((attempt_dir / 'model-graders').exists())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            set_v5_synthetic_host_mode(paths, 'process-timeout')
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['execution']['timeout_seconds'] = 1
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['timeout_seconds'] = 1
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]
            timed_out = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                timed_out.returncode, 3,
                timed_out.stdout + timed_out.stderr,
            )
            sealed = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
                '--resume',
            )
            self.assertEqual(
                sealed.returncode, 3, sealed.stdout + sealed.stderr,
            )
            row = json.loads(index_path.read_text(encoding='utf-8').strip())
            receipt = json.loads(
                (
                    root / plan['artifacts']['root']
                    / row['receipt']['path']
                ).read_text(encoding='utf-8'),
            )
            self.assertEqual('clean', receipt['cleanup']['process'])
            self.assertEqual([], receipt['cleanup']['residue'])

    def test_host_and_grader_invocations_close_environment_and_shell(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan = self._compile_fixture(root)
            plan_path = root / 'execution-plan.json'
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]
            environment = {
                **os.environ,
                'PYTHONDONTWRITEBYTECODE': '1',
                'SHOULD_NOT_REACH_HOST': 'secret-sentinel-value',
            }
            result = self._run_runner(
                plan_path,
                index_path,
                '--entry-id',
                entry['entry_id'],
                environment=environment,
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr,
            )
            row = json.loads(index_path.read_text(encoding='utf-8').strip())
            attempt_dir = (
                root / plan['artifacts']['root'] / row['artifact_dir']
            )
            host_invocation_path = attempt_dir / 'host-invocation.json'
            host_invocation = json.loads(
                host_invocation_path.read_text(encoding='utf-8'),
            )
            self.assertFalse(host_invocation['shell'])
            self.assertTrue(host_invocation['start_new_session'])
            self.assertEqual(
                ['PYTHONDONTWRITEBYTECODE'],
                host_invocation['env_allowlist'],
            )
            self.assertEqual(
                ['PYTHONDONTWRITEBYTECODE'],
                [item['name'] for item in host_invocation['env']],
            )
            self.assertNotIn(
                'secret-sentinel-value',
                host_invocation_path.read_text(encoding='utf-8'),
            )
            grader_invocation = json.loads(
                (
                    attempt_dir
                    / 'graders/fixture-grader/invocation.json'
                ).read_text(encoding='utf-8'),
            )
            self.assertFalse(grader_invocation['shell'])
            self.assertTrue(grader_invocation['start_new_session'])
            self.assertEqual([], grader_invocation['env'])
            self.assertEqual('none', grader_invocation['credential_policy'])

    def test_index_cannot_skip_an_earlier_execute_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan = self._compile_fixture(root)
            plan_path = root / 'execution-plan.json'
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]
            initial = self._run_runner(plan_path, index_path)
            self.assertEqual(
                initial.returncode, 0, initial.stdout + initial.stderr,
            )
            rows = index_path.read_text(encoding='utf-8').splitlines()
            index_path.write_text(rows[1] + '\n', encoding='utf-8')
            invalid_prefix = index_path.read_bytes()

            resumed = self._run_runner(
                plan_path, index_path, '--resume',
            )
            self.assertEqual(
                resumed.returncode, 2, resumed.stdout + resumed.stderr,
            )
            self.assertEqual(invalid_prefix, index_path.read_bytes())

    def test_runner_restores_fixture_and_executes_reset_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            fixture_path = root / 'fixture-input.txt'
            fixture_path.write_text('fixture bytes\n', encoding='utf-8')
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['fixture']['initial_files'] = [{
                'path': fixture_path.name,
                'sha256': (
                    'sha256:' + hashlib.sha256(
                        fixture_path.read_bytes(),
                    ).hexdigest()
                ),
            }]
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            plan_path = root / 'execution-plan.json'
            compile_result = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compile_result.returncode, 0,
                compile_result.stdout + compile_result.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = root / plan['artifacts']['root'] / plan['artifacts'][
                'index_relpath'
            ]

            run_result = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                run_result.returncode, 0,
                run_result.stdout + run_result.stderr,
            )
            row = json.loads(index_path.read_text(encoding='utf-8').strip())
            attempt_dir = (
                root / plan['artifacts']['root'] / row['artifact_dir']
            )
            self.assertEqual(
                fixture_path.read_bytes(),
                (attempt_dir / 'workspace/fixture-input.txt').read_bytes(),
            )
            receipt = json.loads(
                (
                    root / plan['artifacts']['root']
                    / row['receipt']['path']
                ).read_text(encoding='utf-8'),
            )
            self.assertEqual(
                ['probe_capability', 'execute_case'],
                [
                    request['envelope']['request_kind']
                    for request in receipt['host_protocol']['requests']
                ],
            )
            artifact_paths = {
                artifact['path'] for artifact in receipt['artifacts']
            }
            self.assertIn('fixture-initial-manifest.json', artifact_paths)
            self.assertIn('fixture-final-manifest.json', artifact_paths)

    def test_principal_budget_context_and_parent_mutations_fail_closed(
        self,
    ) -> None:
        for mode in (
            'principal-budget-overrun',
            'principal-context-mismatch',
            'principal-cycle',
            'principal-span-mismatch',
            'principal-authority-mismatch',
            'causal-cycle',
            'handoff-transform-missing',
            'handoff-schema-mismatch',
            'handoff-result-missing',
            'handoff-premature-result',
            'duplicate-handoff',
            'partial-join-silent',
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = materialize_v5_handoff_fixture(root)
                set_v5_synthetic_host_mode(paths, mode)
                plan_path = root / 'execution-plan.json'
                compiled = self._run_compiler(paths, plan_path)
                self.assertEqual(
                    compiled.returncode, 0,
                    compiled.stdout + compiled.stderr,
                )
                plan = json.loads(plan_path.read_text(encoding='utf-8'))
                entry = plan['entries'][0]
                index_path = (
                    root / plan['artifacts']['root']
                    / plan['artifacts']['index_relpath']
                )

                result = self._run_runner(
                    plan_path, index_path,
                    '--entry-id', entry['entry_id'],
                )
                self.assertEqual(
                    result.returncode, 2,
                    result.stdout + result.stderr,
                )
                self.assertFalse(index_path.exists())

    def test_async_delivery_preserves_forward_causal_ancestry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_handoff_fixture(root)
            set_v5_synthetic_host_mode(paths, 'async-delivery')
            plan_path = root / 'execution-plan.json'
            compiled = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compiled.returncode, 0, compiled.stdout + compiled.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = (
                root / plan['artifacts']['root']
                / plan['artifacts']['index_relpath']
            )

            result = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr,
            )
            row = json.loads(index_path.read_text(encoding='utf-8').strip())
            receipt = json.loads(
                (
                    root / plan['artifacts']['root']
                    / row['receipt']['path']
                ).read_text(encoding='utf-8'),
            )
            execute_events = receipt['host_protocol']['events']
            self.assertEqual([None, 0], [
                event['parent_seq'] for event in execute_events
            ])
            self.assertEqual([1, 0], [
                event['payload']['delivery_order']
                for event in execute_events
            ])

    def test_fresh_forked_context_proofs_and_principal_bounds(self) -> None:
        def compile_and_run(
            root: Path,
            paths: dict[str, Path],
        ) -> tuple[subprocess.CompletedProcess[str], dict, Path]:
            plan_path = root / 'execution-plan.json'
            compiled = self._run_compiler(paths, plan_path)
            self.assertEqual(
                compiled.returncode, 0, compiled.stdout + compiled.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            entry = plan['entries'][0]
            index_path = (
                root / plan['artifacts']['root']
                / plan['artifacts']['index_relpath']
            )
            result = self._run_runner(
                plan_path, index_path, '--entry-id', entry['entry_id'],
            )
            return result, plan, index_path

        for context_mode in ('fresh', 'forked'):
            with (
                self.subTest(context_mode=context_mode),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                paths = materialize_v5_handoff_fixture(root)
                scenario = json.loads(
                    paths['scenarios'].read_text(encoding='utf-8'),
                )
                scenario['coordination']['principal_slots'][1][
                    'context_mode'
                ] = context_mode
                paths['scenarios'].write_text(
                    json.dumps(scenario, separators=(',', ':')) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                result, plan, index_path = compile_and_run(root, paths)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr,
                )
                row = json.loads(
                    index_path.read_text(encoding='utf-8').strip(),
                )
                receipt = json.loads(
                    (
                        root / plan['artifacts']['root']
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                worker = next(
                    item for item in receipt['principals']
                    if item['slot_id'] == 'worker'
                )
                component_hashes = {
                    item['content_sha256']
                    for item in receipt['context_usage']['components']
                }
                if context_mode == 'fresh':
                    self.assertIsNone(worker['inherited_context_hash'])
                else:
                    self.assertIn(
                        worker['inherited_context_hash'], component_hashes,
                    )

        for bound, value in (('max_width', 1), ('max_depth', 1)):
            with (
                self.subTest(bound=bound),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                paths = materialize_v5_handoff_fixture(root)
                scenario = json.loads(
                    paths['scenarios'].read_text(encoding='utf-8'),
                )
                scenario['coordination'][bound] = value
                if bound == 'max_width':
                    scenario['coordination']['max_in_flight'] = value
                paths['scenarios'].write_text(
                    json.dumps(scenario, separators=(',', ':')) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                result, _, index_path = compile_and_run(root, paths)
                self.assertEqual(
                    result.returncode, 2, result.stdout + result.stderr,
                )
                self.assertFalse(index_path.exists())

    def test_compiler_emits_byte_identical_schema_valid_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            outputs = [root / 'plan-a.json', root / 'plan-b.json']
            results = [
                self.run_cmd(
                    'scripts/compile_eval_plan.py',
                    str(paths['spec']),
                    str(paths['scenarios']),
                    str(paths['host']),
                    '--output', str(output),
                )
                for output in outputs
            ]
            results.append(self._run_compiler(paths, outputs[0]))
            for result in results:
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr,
                )
            self.assertEqual(outputs[0].read_bytes(), outputs[1].read_bytes())
            plan = json.loads(outputs[0].read_text(encoding='utf-8'))

        validator = load_validator_module()
        self.assertEqual(
            [],
            validator.validate_v5_schema(
                plan,
                'execution-plan-v1.schema.json',
                validator.load_v5_schema_registry(),
            ),
        )
        self.assertTrue(
            load_evidence_io_module().verify_self_hash(plan, 'plan_hash'),
        )

    def test_plan_and_entry_ids_counts_and_paths_use_exact_projections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths, plan = self._compile_fixture(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))

        compiler = load_compiler_module()
        plan_projection = {
            'evaluation_id': plan['evaluation_id'],
            'spec_hash': plan['spec_hash'],
            'scenario_corpus_hash': plan['scenario_corpus_hash'],
            'host_manifest_hash': plan['host_manifest_hash'],
            'calibration_hash': plan['calibration_hash'],
            'suite_quality_hash': plan['suite_quality_hash'],
            'compiler_algorithm': plan['compiler']['algorithm'],
            'compiler_version': plan['compiler']['version'],
            'compiler_source_hash': plan['compiler']['source_hash'],
        }
        self.assertEqual(
            'pl-' + compiler._projection_digest(plan_projection).hex()[:24],
            plan['plan_id'],
        )
        self.assertEqual(
            {
                'total': 2,
                'execute': 2,
                'unsupported': 0,
                'not_evaluable': 0,
            },
            plan['expected_counts'],
        )
        self.assertEqual({'outcome': 2, 'safety': 2}, plan['dimension_coverage'])
        self.assertIsNone(plan['calibration_hash'])
        self.assertEqual(
            list(range(len(plan['entries']))),
            [entry['entry_ordinal'] for entry in plan['entries']],
        )
        self.assertEqual(
            len(plan['entries']),
            len({entry['entry_id'] for entry in plan['entries']}),
        )
        treatments = {
            item['treatment_id']: item for item in plan['treatments']
        }
        for entry in plan['entries']:
            projection = compiler._entry_projection(
                spec=compiler._normalize_spec(spec),
                scenario=entry['execute_case_payload']['case'],
                treatment=treatments[entry['treatment_id']],
                repeat=entry['repeat'],
                spec_hash=plan['spec_hash'],
                scenario_corpus_hash=plan['scenario_corpus_hash'],
                host_manifest_hash=plan['host_manifest_hash'],
                calibration_hash=plan['calibration_hash'],
                suite_quality_hash=plan['suite_quality_hash'],
                catalog_hash=entry['catalog_hash'],
            )
            self.assertEqual(
                'pe-' + compiler._projection_digest(projection).hex()[:24],
                entry['entry_id'],
            )
            self.assertEqual(
                'entries/' + entry['entry_id'],
                entry['artifact_relpath'],
            )
            self.assertEqual(
                'workspaces/' + entry['entry_id'],
                entry['execute_case_payload']['workspace'],
            )

    def test_set_like_spec_reordering_is_byte_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, baseline = self._compile_fixture(root)
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['subject']['mechanisms'].reverse()
            spec['applicability'].reverse()
            spec['treatments'].reverse()
            spec['authority']['runner_capabilities'].reverse()
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            output = root / 'reordered.json'
            result = self._run_compiler(paths, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            reordered = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(baseline, reordered)

    def test_ordered_turn_and_catalog_changes_alter_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            turn_paths, turn_baseline = self._compile_fixture(root / 'turn')
            scenario = json.loads(
                turn_paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['turns'][0]['input']['content'] += ' Ordered change.'
            turn_paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(turn_paths)
            turn_output = root / 'turn' / 'changed.json'
            turn_result = self._run_compiler(turn_paths, turn_output)
            self.assertEqual(
                turn_result.returncode,
                0,
                turn_result.stdout + turn_result.stderr,
            )
            changed_turn = json.loads(
                turn_output.read_text(encoding='utf-8'),
            )

            catalog_paths, catalog_baseline = self._compile_fixture(
                root / 'catalog',
            )
            host = json.loads(
                catalog_paths['host'].read_text(encoding='utf-8'),
            )
            extra = copy.deepcopy(host['catalog']['entries'][0])
            extra.update({
                'id': 'other-skill',
                'name': 'Other Skill',
                'root_hash': canonical_hash({'skill': 'other'}),
            })
            host['catalog']['entries'].append(extra)
            catalog_hash = canonical_hash(host['catalog']['entries'])
            host['catalog']['catalog_hash'] = catalog_hash
            host['identity']['execution']['catalog_hash'] = catalog_hash
            catalog_paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            spec = json.loads(
                catalog_paths['spec'].read_text(encoding='utf-8'),
            )
            for treatment in spec['treatments']:
                treatment['base_catalog_hash'] = catalog_hash
            catalog_paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(catalog_paths)
            catalog_output = root / 'catalog' / 'changed.json'
            catalog_result = self._run_compiler(
                catalog_paths, catalog_output,
            )
            self.assertEqual(
                catalog_result.returncode,
                0,
                catalog_result.stdout + catalog_result.stderr,
            )
            changed_catalog = json.loads(
                catalog_output.read_text(encoding='utf-8'),
            )
        self.assertNotEqual(turn_baseline['plan_hash'], changed_turn['plan_hash'])
        self.assertNotEqual(
            catalog_baseline['plan_hash'], changed_catalog['plan_hash'],
        )

    def test_ordered_state_transition_change_alters_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_stateful_fixture(root)
            first_output = root / 'first.json'
            first = self._run_compiler(paths, first_output)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_plan = json.loads(first_output.read_text(encoding='utf-8'))

            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['state_model']['allowed_transition_ids'].reverse()
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            second_output = root / 'second.json'
            second = self._run_compiler(paths, second_output)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            second_plan = json.loads(second_output.read_text(encoding='utf-8'))
        self.assertNotEqual(first_plan['plan_hash'], second_plan['plan_hash'])

    def test_principal_context_tool_policy_and_observation_bind_plan_hash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_handoff_fixture(root)

            def compile_hash(name: str) -> str:
                output = root / f'{name}.json'
                result = self._run_compiler(paths, output)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr,
                )
                return json.loads(
                    output.read_text(encoding='utf-8'),
                )['plan_hash']

            hashes = [compile_hash('baseline')]
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['coordination']['principal_slots'][1]['role'] = (
                'specialist'
            )
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            hashes.append(compile_hash('principal'))

            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['coordination']['topology'] = 'hybrid'
            scenario['execution_context']['expected_tools'] = ['fixture-tool']
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            probe_template = host['capabilities'][0]
            for capability in (
                'action_authorization_trace',
                'render_effect_capture',
                'tool_schema_model_visible_capture',
            ):
                record = copy.deepcopy(probe_template)
                record['capability'] = capability
                host['capabilities'].append(record)
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            hashes.append(compile_hash('topology-context'))

            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            new_tool_policy = canonical_hash({'tool-policy': 'changed'})
            for treatment in spec['treatments']:
                treatment['tool_policy_hash'] = new_tool_policy
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            hashes.append(compile_hash('tool-policy'))

            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            host['policy']['filesystem']['rules'].append('changed-policy')
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            hashes.append(compile_hash('host-policy'))

            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['observation_contracts'] = [{
                'observation_id': 'outcome-observation',
                'producer': 'synthetic-host',
                'capture_authority': 'host-manifest',
                'artifact': 'host-manifest-v1.json',
                'locator': {
                    'kind': 'text_lines',
                    'artifact': 'host-manifest-v1.json',
                    'start_line': 1,
                    'end_line': 1,
                },
                'encoding': 'utf-8',
                'schema_hash': None,
                'expected_hash': (
                    'sha256:'
                    + hashlib.sha256(paths['host'].read_bytes()).hexdigest()
                ),
                'predicate': None,
                'valid_from_seq': 0,
                'valid_until_seq': 1,
                'valid_from_utc': None,
                'valid_until_utc': None,
                'freshness_requirement': 'captured during the attempt',
                'clock_requirement': 'monotonic sequence',
                'consumer_requirement_ids': ['outcome'],
            }]
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            hashes.append(compile_hash('observation'))
        self.assertEqual(len(hashes), len(set(hashes)))

    def test_probe_status_derives_exact_disposition_and_execute_only_authority(
        self,
    ) -> None:
        expected = {
            'pass': ('execute', 'feasible'),
            'unsupported': ('unsupported', 'unsupported'),
            'unknown': ('not_evaluable', 'not_evaluable'),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for status, (disposition, derived) in expected.items():
                case_root = root / status
                paths = materialize_v5_contract_fixture(case_root)
                host = json.loads(
                    paths['host'].read_text(encoding='utf-8'),
                )
                host['capabilities'][0]['probe']['status'] = status
                paths['host'].write_text(
                    json.dumps(host, indent=2) + '\n',
                    encoding='utf-8',
                )
                spec = json.loads(
                    paths['spec'].read_text(encoding='utf-8'),
                )
                if status != 'pass':
                    spec['authority']['runner_capabilities'] = []
                paths['spec'].write_text(
                    json.dumps(spec, indent=2) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                output = case_root / 'plan.json'
                result = self._run_compiler(paths, output)
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr,
                )
                plan = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(
                    {disposition},
                    {entry['disposition'] for entry in plan['entries']},
                )
                self.assertEqual(
                    {derived},
                    {
                        entry['feasibility']['derived_status']
                        for entry in plan['entries']
                    },
                )

            missing_paths = materialize_v5_contract_fixture(
                root / 'missing-authority',
            )
            spec = json.loads(
                missing_paths['spec'].read_text(encoding='utf-8'),
            )
            spec['authority']['runner_capabilities'] = []
            missing_paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(missing_paths)
            missing = self._run_compiler(
                missing_paths,
                root / 'missing-authority' / 'plan.json',
            )
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn('authority.missing_execute', missing.stderr)

    def test_unknown_probe_has_priority_over_unsupported_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            host['capabilities'][0]['probe']['status'] = 'unknown'
            unsupported = copy.deepcopy(host['capabilities'][0])
            unsupported['capability'] = 'composition'
            unsupported['probe']['status'] = 'unsupported'
            host['capabilities'].append(unsupported)
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['host']['required_capabilities'].append('composition')
            spec['authority']['runner_capabilities'] = []
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            output = root / 'plan.json'
            result = self._run_compiler(paths, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plan = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(
            {'not_evaluable'},
            {entry['disposition'] for entry in plan['entries']},
        )

    def test_model_grading_is_calibration_bound_blinded_and_capability_gated(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_model_ready_fixture(root)
            output = root / 'plan.json'
            result = self._run_compiler(paths, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plan = json.loads(output.read_text(encoding='utf-8'))
        self.assertIsNotNone(plan['calibration_hash'])
        self.assertEqual({'execute'}, {
            entry['disposition'] for entry in plan['entries']
        })
        for entry in plan['entries']:
            self.assertIn('model_grading', entry['required_capabilities'])
            self.assertEqual(1, len(entry['model_grade_specs']))
            projection = entry['model_grade_specs'][0]['blinded_projection']
            self.assertNotIn('treatment_id', projection)
            self.assertNotIn('treatment', projection)
            self.assertNotIn('causal_role', projection)
            self.assertNotIn('profile', projection)

    def test_compiler_never_starts_host_or_grader_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            sentinel = root / 'process-started'
            executable = root / 'must-not-run.py'
            executable.write_text(
                (
                    '#!/usr/bin/env python3\n'
                    'from pathlib import Path\n'
                    f'Path({str(sentinel)!r}).write_text("started")\n'
                ),
                encoding='utf-8',
            )
            executable_hash = (
                'sha256:' + hashlib.sha256(executable.read_bytes()).hexdigest()
            )
            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            host['command']['argv'] = [sys.executable, str(executable)]
            host['command']['resolved_executable'] = sys.executable
            host['command']['executable_sha256'] = (
                'sha256:'
                + hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
            )
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['graders'][0]['verifier'].update({
                'argv': [sys.executable, str(executable)],
                'path': executable.name,
                'sha256': executable_hash,
            })
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            result = self._run_compiler(paths, root / 'plan.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(sentinel.exists())

    def test_hash_profile_module_and_capability_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results: dict[str, subprocess.CompletedProcess[str]] = {}

            hash_paths = materialize_v5_contract_fixture(root / 'hash')
            with hash_paths['scenarios'].open('ab') as stream:
                stream.write(b'\n')
            results['hash'] = self._run_compiler(
                hash_paths, root / 'hash' / 'plan.json',
            )

            module_paths = materialize_v5_contract_fixture(root / 'module')
            spec = json.loads(
                module_paths['spec'].read_text(encoding='utf-8'),
            )
            spec['applicability'][0]['status'] = 'not_applicable'
            module_paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(module_paths)
            results['module'] = self._run_compiler(
                module_paths, root / 'module' / 'plan.json',
            )

            profile_paths = materialize_v5_contract_fixture(root / 'profile')
            spec = json.loads(
                profile_paths['spec'].read_text(encoding='utf-8'),
            )
            candidate = next(
                item for item in spec['treatments']
                if item['causal_role'] == 'candidate'
            )
            candidate['profile'] = 'candidate/natural_routing'
            profile_paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            results['profile'] = self._run_compiler(
                profile_paths, root / 'profile' / 'plan.json',
            )

            capability_paths = materialize_v5_contract_fixture(
                root / 'capability',
            )
            host = json.loads(
                capability_paths['host'].read_text(encoding='utf-8'),
            )
            host['capabilities'][0]['capability'] = 'composition'
            capability_paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(capability_paths)
            results['capability'] = self._run_compiler(
                capability_paths, root / 'capability' / 'plan.json',
            )

        expected_codes = {
            'hash': 'binding.hash_mismatch',
            'module': 'applicability.shape_mismatch',
            'profile': 'applicability.shape_mismatch',
            'capability': 'host.probe_missing',
        }
        for name, result in results.items():
            self.assertEqual(
                result.returncode,
                1,
                f'{name}: {result.stdout}{result.stderr}',
            )
            self.assertIn(expected_codes[name], result.stderr)

    def test_truncated_projection_collision_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            compiler = load_compiler_module()
            spec, scenarios, host, _ = compiler._load_ready_contract(
                paths['spec'], paths['scenarios'], paths['host'],
            )
            with self.assertRaises(compiler.ContractFailure) as raised:
                compiler.compile_plan(
                    spec,
                    scenarios,
                    host,
                    spec_path=paths['spec'],
                    source_path=ROOT / 'scripts/compile_eval_plan.py',
                    digest_fn=lambda _: b'\x00' * 32,
                )
        self.assertEqual(
            'compiler.entry_id_collision',
            raised.exception.code,
        )

    def test_plan_has_frozen_toolchain_and_no_runtime_outcome_or_temp_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan = self._compile_fixture(root)
            serialized = json.dumps(plan, sort_keys=True)

        executable = Path(sys.executable).resolve()
        self.assertEqual(
            str(executable), plan['compiler']['python_executable'],
        )
        self.assertEqual(
            'sha256:' + hashlib.sha256(executable.read_bytes()).hexdigest(),
            plan['compiler']['python_executable_hash'],
        )
        self.assertEqual(
            (
                'sha256:'
                + hashlib.sha256(
                    (ROOT / 'scripts/compile_eval_plan.py').read_bytes(),
                ).hexdigest()
            ),
            plan['compiler']['source_hash'],
        )
        self.assertNotIn(str(root), serialized)

        forbidden_keys = {
            'attempt',
            'run_id',
            'receipt_path',
            'timestamp',
            'score',
            'runtime_outcome',
            'secret',
        }

        def collect_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | {
                    key
                    for child in value.values()
                    for key in collect_keys(child)
                }
            if isinstance(value, list):
                return {
                    key
                    for child in value
                    for key in collect_keys(child)
                }
            return set()

        self.assertFalse(forbidden_keys & collect_keys(plan))
        self.assertNotIn('outcome', plan)
        self.assertTrue(
            all('outcome' not in entry for entry in plan['entries']),
        )

    def test_causal_estimand_treatments_must_cover_the_same_matrix_cells(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            candidate = next(
                treatment for treatment in spec['treatments']
                if treatment['causal_role'] == 'candidate'
            )
            candidate['exclusions'] = ['case-basic']
            candidate['exclusion_reason'] = 'intentional mismatch'
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            result = self._run_compiler(paths, root / 'plan.json')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('compiler.causal_matrix', result.stderr)

    def test_case_treatment_repeat_matrix_expands_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_contract_fixture(root)
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['suite']['repeats'] = 2
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            output = root / 'plan.json'
            result = self._run_compiler(paths, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plan = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(4, plan['expected_counts']['total'])
        cells = {
            (
                entry['case_id'],
                entry['treatment_id'],
                entry['repeat'],
            )
            for entry in plan['entries']
        }
        self.assertEqual(4, len(cells))
        self.assertEqual({1, 2}, {cell[2] for cell in cells})

    def test_compiler_rejects_nonready_and_placeholder_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nonready_paths = materialize_v5_contract_fixture(
                root / 'nonready',
            )
            spec = json.loads(
                nonready_paths['spec'].read_text(encoding='utf-8'),
            )
            spec['execution']['ready'] = False
            nonready_paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            nonready = self._run_compiler(
                nonready_paths, root / 'nonready' / 'plan.json',
            )

            placeholder_paths = materialize_v5_contract_fixture(
                root / 'placeholder',
            )
            spec = json.loads(
                placeholder_paths['spec'].read_text(encoding='utf-8'),
            )
            spec['graders'][0]['verifier']['argv'] = [
                'replace-with-grader',
            ]
            placeholder_paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(placeholder_paths)
            placeholder = self._run_compiler(
                placeholder_paths, root / 'placeholder' / 'plan.json',
            )
        self.assertEqual(
            nonready.returncode, 1, nonready.stdout + nonready.stderr,
        )
        self.assertIn('compiler.not_ready', nonready.stderr)
        self.assertEqual(
            placeholder.returncode,
            1,
            placeholder.stdout + placeholder.stderr,
        )
        self.assertIn('readiness.verifier_placeholder', placeholder.stderr)

    def test_rehashed_semantic_tamper_and_conflicting_output_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths, plan = self._compile_fixture(root)
            output = root / 'execution-plan.json'
            compiler = load_compiler_module()
            tampered = copy.deepcopy(plan)
            tampered['entries'][0]['timeout_seconds'] += 1
            tampered['plan_hash'] = compiler.canonical_self_hash(
                tampered, 'plan_hash',
            )
            spec, scenarios, host, registry = compiler._load_ready_contract(
                paths['spec'], paths['scenarios'], paths['host'],
            )
            with self.assertRaises(compiler.ContractFailure) as raised:
                compiler.validate_compiled_plan(
                    tampered,
                    spec,
                    scenarios,
                    host,
                    spec_path=paths['spec'],
                    source_path=ROOT / 'scripts/compile_eval_plan.py',
                    registry=registry,
                )
            tampered_bytes = compiler.canonical_json_bytes(tampered)
            output.write_bytes(tampered_bytes)
            conflict = self._run_compiler(paths, output)
            preserved = output.read_bytes()
        self.assertEqual('compiler.plan_semantics', raised.exception.code)
        self.assertEqual(conflict.returncode, 1, conflict.stdout + conflict.stderr)
        self.assertIn('compiler.plan_id_collision', conflict.stderr)
        self.assertEqual(tampered_bytes, preserved)

    def test_committed_plan_golden_is_exact_compiler_output(self) -> None:
        golden_path = (
            Path(__file__).resolve().parent
            / 'fixtures/skill_evaluator/execution-plan-v1.json'
        )
        golden = json.loads(golden_path.read_text(encoding='utf-8'))
        runtime = {
            key: golden['compiler'][key]
            for key in (
                'python_executable',
                'python_version',
                'python_executable_hash',
            )
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_contract_fixture(Path(tmp))
            compiler = load_compiler_module()
            spec, scenarios, host, registry = compiler._load_ready_contract(
                paths['spec'], paths['scenarios'], paths['host'],
            )
            regenerated = compiler.compile_plan(
                spec,
                scenarios,
                host,
                spec_path=paths['spec'],
                source_path=ROOT / 'scripts/compile_eval_plan.py',
                runtime_override=runtime,
            )
            self.assertEqual(
                golden_path.read_bytes(),
                compiler.canonical_json_bytes(regenerated),
            )
            compiler.validate_compiled_plan(
                golden,
                spec,
                scenarios,
                host,
                spec_path=paths['spec'],
                source_path=ROOT / 'scripts/compile_eval_plan.py',
                registry=registry,
                runtime_override=runtime,
            )


if __name__ == '__main__':
    unittest.main()
