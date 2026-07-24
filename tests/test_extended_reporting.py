from __future__ import annotations

from unittest import mock

from skill_evaluator_test_support import *  # noqa: F403


def material_failure_records(
    baseline_failures: set[str],
    candidate_failures: set[str],
) -> list[dict]:
    rows = []
    for variant, failures in (
        ("baseline", baseline_failures),
        ("candidate", candidate_failures),
    ):
        for case_id in ("a", "b", "c", "d"):
            for repeat in (1, 2):
                rows.append({
                    "variant": variant,
                    "case_id": case_id,
                    "repeat": repeat,
                    "valid": True,
                    "task_pass": case_id not in failures,
                    "safety_pass": True,
                    "hard_gate_failures": (
                        ["material-contract"] if case_id in failures else []
                    ),
                })
    return rows


class TestExtendedReporting(SkillEvaluatorTestCase):  # noqa: F405
    def _materialize_v5_analysis_bundle(
        self,
        root: Path,
        *,
        manual_required: bool = False,
        failure_index_budget: int | None = None,
        level: str = 'L1',
        case_count: int = 1,
    ) -> dict[str, Path]:
        paths = materialize_v5_contract_fixture(root)
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        spec['level'] = level
        spec['execution']['mode'] = (
            'diagnostic' if level in {'L0', 'L1'} else 'scored'
        )
        if case_count > 1:
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            case_ids = [f'case-{index}' for index in range(1, case_count + 1)]
            scenarios = []
            for case_id in case_ids:
                copy_of_scenario = copy.deepcopy(scenario)
                copy_of_scenario['case_id'] = case_id
                scenarios.append(copy_of_scenario)
            paths['scenarios'].write_text(
                ''.join(
                    json.dumps(item, separators=(',', ':')) + '\n'
                    for item in scenarios
                ),
                encoding='utf-8',
            )
            for treatment in spec['treatments']:
                treatment['scenario_ids'] = case_ids
            proof = json.loads(
                paths['quality_proof'].read_text(encoding='utf-8'),
            )
            proof['golden'] = {
                'case_ids': case_ids,
                'passed_ids': case_ids,
            }
            proof['case_classes'] = [
                {'case_id': case_id, 'class': case_class}
                for case_id in case_ids
                for case_class in ('positive', 'boundary_or_failure')
            ]
            proof['provenance_clusters'][0]['case_ids'] = case_ids
            validator = load_validator_module()
            proof['duplicate_groups'] = [
                {
                    'group_id': f'{kind}-{index}',
                    'kind': kind,
                    'case_ids': sorted(group),
                    'status': 'allowed',
                    'review_locator': None,
                }
                for kind in ('exact', 'prompt_overlap', 'fixture_overlap')
                for index, group in enumerate(
                    validator._derive_duplicate_groups(scenarios, kind),
                    start=1,
                )
            ]
            paths['quality_proof'].write_text(
                json.dumps(proof, indent=2) + '\n',
                encoding='utf-8',
            )
        if manual_required:
            role = 'independent-evaluator'
            required_evidence = ['outcome-review']
            spec['authority']['manual_review'] = {
                'required': True,
                'role': role,
                'decision_contract_hash': canonical_hash({
                    'reviewer_role': role,
                    'required_evidence': required_evidence,
                }),
            }
        if failure_index_budget is not None:
            spec['artifacts']['failure_index_budget'] = failure_index_budget
        paths['spec'].write_text(
            json.dumps(spec, indent=2) + '\n',
            encoding='utf-8',
        )
        rebind_v5_contract_fixture(paths)
        paths.update({
            'plan': root / 'execution-plan.json',
            'index': root / 'artifacts/index.jsonl',
            'summary': root / 'summary.json',
            'failures': root / 'failures.json',
            'markdown': root / 'summary.md',
        })
        compiled = self.call_cli(
            'scripts/compile_eval_plan.py',
            str(paths['spec']),
            str(paths['scenarios']),
            str(paths['host']),
            '--output', str(paths['plan']),
        )
        self.assertEqual(
            compiled.returncode, 0, compiled.stdout + compiled.stderr,
        )
        executed = self.call_cli(
            'scripts/run_eval_plan.py',
            str(paths['plan']),
            '--index', str(paths['index']),
        )
        self.assertEqual(
            executed.returncode, 0, executed.stdout + executed.stderr,
        )
        return paths

    def _rewrite_v5_outcomes(
        self,
        paths: dict[str, Path],
        failing_keys: set[tuple[str, str]],
    ) -> None:
        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
        artifacts_root = paths['plan'].parent / plan['artifacts']['root']
        rows = [
            json.loads(line)
            for line in paths['index'].read_text(encoding='utf-8').splitlines()
        ]
        for row in rows:
            if (row['treatment_id'], row['case_id']) not in failing_keys:
                continue
            attempt_root = artifacts_root / row['artifact_dir']
            receipt_path = artifacts_root / row['receipt']['path']
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            reference = receipt['grader_outputs'][0]['output']
            output_path = attempt_root / reference['path']
            output = json.loads(output_path.read_text(encoding='utf-8'))
            next(
                item for item in output['checks']
                if item['check_id'] == 'outcome-check'
            )['pass'] = False
            output['overall_pass'] = False
            output['score'] = 50
            output_path.write_text(
                json.dumps(output, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            output_hash = (
                'sha256:' + hashlib.sha256(output_path.read_bytes()).hexdigest()
            )
            reference['sha256'] = output_hash
            next(
                item for item in receipt['artifacts']
                if item['path'] == reference['path']
            )['sha256'] = output_hash
            invocation_reference = receipt['grader_outputs'][0]['invocation']
            invocation_path = attempt_root / invocation_reference['path']
            invocation = json.loads(
                invocation_path.read_text(encoding='utf-8'),
            )
            invocation['exit_code'] = next(
                code for code in range(256)
                if code not in invocation['pass_exit_codes']
            )
            invocation_path.write_text(
                json.dumps(invocation, sort_keys=True, separators=(',', ':')),
                encoding='utf-8',
            )
            invocation_hash = (
                'sha256:'
                + hashlib.sha256(invocation_path.read_bytes()).hexdigest()
            )
            invocation_reference['sha256'] = invocation_hash
            next(
                item for item in receipt['artifacts']
                if item['path'] == invocation_reference['path']
            )['sha256'] = invocation_hash
            receipt['receipt_hash'] = canonical_hash({
                key: value for key, value in receipt.items()
                if key != 'receipt_hash'
            })
            receipt_path.write_text(
                json.dumps(receipt, sort_keys=True, separators=(',', ':')),
                encoding='utf-8',
            )
            row['receipt']['sha256'] = (
                'sha256:' + hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            )
        paths['index'].write_text(
            ''.join(
                json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n'
                for row in rows
            ),
            encoding='utf-8',
        )

    def _mutate_first_v5_receipt(
        self,
        paths: dict[str, Path],
        mutation: Callable[[dict], None],
    ) -> None:
        plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
        artifacts_root = paths['plan'].parent / plan['artifacts']['root']
        rows = [
            json.loads(line)
            for line in paths['index'].read_text(encoding='utf-8').splitlines()
        ]
        row = rows[0]
        receipt_path = artifacts_root / row['receipt']['path']
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        mutation(receipt)
        receipt['receipt_hash'] = canonical_hash({
            key: value for key, value in receipt.items()
            if key != 'receipt_hash'
        })
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, separators=(',', ':')),
            encoding='utf-8',
        )
        row['receipt']['sha256'] = (
            'sha256:' + hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        )
        paths['index'].write_text(
            ''.join(
                json.dumps(item, sort_keys=True, separators=(',', ':')) + '\n'
                for item in rows
            ),
            encoding='utf-8',
        )

    def _materialize_v5_runtime_fixture(
        self,
        root: Path,
        materializer: Callable[[Path], dict[str, Path]],
    ) -> dict[str, Path]:
        paths = materializer(root)
        plan_path = root / 'execution-plan.json'
        compiled = self.call_cli(
            'scripts/compile_eval_plan.py',
            str(paths['spec']),
            str(paths['scenarios']),
            str(paths['host']),
            '--output', str(plan_path),
        )
        self.assertEqual(
            0, compiled.returncode, compiled.stdout + compiled.stderr,
        )
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        index_path = (
            root / plan['artifacts']['root']
            / plan['artifacts']['index_relpath']
        )
        executed = self.call_cli(
            'scripts/run_eval_plan.py',
            str(plan_path),
            '--index', str(index_path),
        )
        self.assertEqual(
            0, executed.returncode, executed.stdout + executed.stderr,
        )
        paths.update({
            'plan': plan_path,
            'index': index_path,
            'summary': root / 'summary.json',
            'failures': root / 'failures.json',
        })
        return paths

    def _run_v5_fixture_analysis(
        self,
        root: Path,
        materializer: Callable[[Path], dict[str, Path]],
    ) -> dict:
        paths = self._materialize_v5_runtime_fixture(root, materializer)
        summary_path = root / 'summary.json'
        analyzed = self.call_cli(
            'scripts/analyze_runs.py',
            str(paths['index']),
            '--spec', str(paths['spec']),
            '--json', str(summary_path),
            '--failure-index', str(root / 'failures.json'),
        )
        self.assertIn(
            analyzed.returncode, {0, 1, 3},
            analyzed.stdout + analyzed.stderr,
        )
        return json.loads(summary_path.read_text(encoding='utf-8'))

    def test_v5_analyzer_writes_compact_bound_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_v5_analysis_bundle(Path(tmp))
            result = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
                '--markdown', str(paths['markdown']),
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr,
            )
            summary = json.loads(
                paths['summary'].read_text(encoding='utf-8'),
            )
            failures = json.loads(
                paths['failures'].read_text(encoding='utf-8'),
            )
            validator = load_validator_module()
            registry = validator.load_v5_schema_registry()
            self.assertEqual([], validator.validate_v5_schema(
                summary, 'analysis-summary-v4.schema.json', registry,
            ))
            self.assertEqual([], validator.validate_v5_schema(
                failures, 'failure-index-v1.schema.json', registry,
            ))
            self.assertTrue(
                load_evidence_io_module().verify_self_hash(
                    summary, 'summary_hash',
                ),
            )
            self.assertTrue(
                load_evidence_io_module().verify_self_hash(
                    failures, 'failure_index_hash',
                ),
            )
            self.assertTrue(summary['analysis_ready'])
            self.assertNotIn('run_matrix', summary)
            self.assertEqual('applicable', summary['applicability_status'])
            self.assertEqual('feasible', summary['feasibility_status'])
            self.assertEqual('complete', summary['evidence_status'])
            self.assertEqual('not_evaluable', summary['usefulness_status'])
            self.assertEqual(0, failures['item_count'])
            for key, path_key in (
                ('failure_index', 'failures'),
                ('markdown', 'markdown'),
            ):
                manifest = summary['output_manifest'][key]
                self.assertEqual(
                    'sha256:' + hashlib.sha256(
                        paths[path_key].read_bytes(),
                    ).hexdigest(),
                    manifest['sha256'],
                )

    def test_v5_analyzer_never_starts_host_grader_or_verifier_processes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_v5_analysis_bundle(Path(tmp))
            with (
                mock.patch(
                    'subprocess.Popen',
                    side_effect=AssertionError('analyzer started a process'),
                ),
                mock.patch(
                    'subprocess.run',
                    side_effect=AssertionError('analyzer started a process'),
                ),
            ):
                analyzed = self.call_cli(
                    'scripts/analyze_runs.py',
                    str(paths['index']),
                    '--spec', str(paths['spec']),
                    '--json', str(paths['summary']),
                    '--failure-index', str(paths['failures']),
                )
        self.assertEqual(
            0, analyzed.returncode, analyzed.stdout + analyzed.stderr,
        )

    def test_v5_model_grader_uses_bound_calibration_and_raw_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = self._run_v5_fixture_analysis(
                Path(tmp), materialize_v5_model_ready_fixture,
            )
        self.assertEqual('complete', summary['evidence_status'])
        self.assertEqual('pass', summary['suite_quality_status'])
        self.assertEqual('pass', summary['calibration_status'])
        self.assertEqual('pass', summary['independence_summary']['status'])
        self.assertEqual(
            'independent',
            summary['independence_summary']['metrics']['derived_status'],
        )

    def test_v5_model_batch_binding_tamper_is_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_runtime_fixture(
                root, materialize_v5_model_ready_fixture,
            )
            self._mutate_first_v5_receipt(
                paths,
                lambda receipt: receipt['grader_outputs'][0].update({
                    'schedule_hash': 'sha256:' + '0' * 64,
                }),
            )
            analyzed = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
            )
            summary = json.loads(
                paths['summary'].read_text(encoding='utf-8'),
            )
            failures = json.loads(
                paths['failures'].read_text(encoding='utf-8'),
            )
        self.assertEqual(3, analyzed.returncode, analyzed.stdout + analyzed.stderr)
        self.assertEqual('invalid', summary['evidence_status'])
        self.assertTrue(any(
            'schedule hash differs' in item['observed']
            for item in failures['failures']
        ))

    def test_v5_model_attempt_must_remain_inside_calibration_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_runtime_fixture(
                root, materialize_v5_model_ready_fixture,
            )
            calibration = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )

            def expire(receipt: dict) -> None:
                receipt['run']['started_at'] = calibration['expires']
                receipt['run']['ended_at'] = calibration['expires']

            self._mutate_first_v5_receipt(paths, expire)
            analyzed = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
            )
            summary = json.loads(
                paths['summary'].read_text(encoding='utf-8'),
            )
            failures = json.loads(
                paths['failures'].read_text(encoding='utf-8'),
            )
        self.assertEqual(3, analyzed.returncode, analyzed.stdout + analyzed.stderr)
        self.assertEqual('invalid', summary['evidence_status'])
        self.assertTrue(any(
            'outside the calibration window' in item['observed']
            for item in failures['failures']
        ))

    def test_v5_nonexecute_probe_results_are_complete_without_attempts(self) -> None:
        for probe_status, feasibility in (
            ('unsupported', 'unsupported'),
            ('unknown', 'not_evaluable'),
        ):
            with self.subTest(probe_status=probe_status), (
                tempfile.TemporaryDirectory()
            ) as tmp:
                root = Path(tmp)
                paths = materialize_v5_contract_fixture(root)
                host = json.loads(paths['host'].read_text(encoding='utf-8'))
                host['capabilities'][0]['probe']['status'] = probe_status
                paths['host'].write_text(
                    json.dumps(host, indent=2) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                plan_path = root / 'execution-plan.json'
                compiled = self.call_cli(
                    'scripts/compile_eval_plan.py',
                    str(paths['spec']),
                    str(paths['scenarios']),
                    str(paths['host']),
                    '--output', str(plan_path),
                )
                self.assertEqual(
                    0, compiled.returncode, compiled.stdout + compiled.stderr,
                )
                index_path = root / 'artifacts/index.jsonl'
                summary_path = root / 'summary.json'
                failures_path = root / 'failures.json'
                analyzed = self.call_cli(
                    'scripts/analyze_runs.py',
                    str(index_path),
                    '--spec', str(paths['spec']),
                    '--json', str(summary_path),
                    '--failure-index', str(failures_path),
                    '--report-only',
                )
                self.assertEqual(
                    3, analyzed.returncode, analyzed.stdout + analyzed.stderr,
                )
                summary = json.loads(
                    summary_path.read_text(encoding='utf-8'),
                )
                failures = json.loads(
                    failures_path.read_text(encoding='utf-8'),
                )
                self.assertTrue(summary['analysis_ready'])
                self.assertEqual('complete', summary['evidence_status'])
                self.assertEqual(feasibility, summary['feasibility_status'])
                self.assertEqual(
                    'blocked', summary['final_authority_status'],
                )
                self.assertEqual(0, summary['counts']['attempts'])
                self.assertEqual(0, summary['counts']['execute_entries'])
                self.assertFalse((root / 'artifacts').exists())
                self.assertEqual(3, failures['item_count'])
                self.assertEqual(
                    2,
                    sum(
                        item['code'] == 'apparatus.incomplete'
                        for item in failures['failures']
                    ),
                )
                self.assertEqual(
                    {'verified'},
                    {
                        item['evidence_state']
                        for item in failures['failures']
                    },
                )

    def test_v5_missing_execute_receipt_is_indexed_evidence_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_v5_analysis_bundle(Path(tmp))
            rows = paths['index'].read_text(encoding='utf-8').splitlines()
            paths['index'].write_text(rows[0] + '\n', encoding='utf-8')
            result = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
            )
            self.assertEqual(3, result.returncode, result.stdout + result.stderr)
            summary = json.loads(paths['summary'].read_text(encoding='utf-8'))
            failures = json.loads(paths['failures'].read_text(encoding='utf-8'))
            self.assertFalse(summary['analysis_ready'])
            self.assertEqual('incomplete', summary['evidence_status'])
            self.assertEqual(1, failures['item_count'])
            failure = failures['failures'][0]
            self.assertEqual('apparatus.incomplete', failure['code'])
            self.assertEqual('missing', failure['evidence_state'])
            self.assertEqual('json_pointer', failure['locator']['kind'])

    def test_v5_invalid_receipt_forms_reportable_invalid_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_analysis_bundle(root)
            plan = json.loads(paths['plan'].read_text(encoding='utf-8'))
            rows = [
                json.loads(line)
                for line in paths['index'].read_text(encoding='utf-8').splitlines()
            ]
            receipt_path = (
                root / plan['artifacts']['root'] / rows[0]['receipt']['path']
            )
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            receipt['receipt_hash'] = 'sha256:' + '0' * 64
            receipt_path.write_text(
                json.dumps(receipt, separators=(',', ':')),
                encoding='utf-8',
            )
            rows[0]['receipt']['sha256'] = (
                'sha256:' + hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            )
            paths['index'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in rows
                ),
                encoding='utf-8',
            )
            result = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
                '--report-only',
            )
            self.assertEqual(3, result.returncode, result.stdout + result.stderr)
            summary = json.loads(paths['summary'].read_text(encoding='utf-8'))
            failures = json.loads(paths['failures'].read_text(encoding='utf-8'))
            self.assertEqual('invalid', summary['evidence_status'])
            self.assertFalse(summary['analysis_ready'])
            self.assertIn(
                'integrity.invalid',
                {item['code'] for item in failures['failures']},
            )

    def test_v5_failure_identity_locator_dedup_and_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = Path(tmp) / 'evidence.json'
            text = '{"value":1}\n'
            artifact_path.write_text(text, encoding='utf-8')
            artifacts = {
                'evidence.json': {
                    'resolved': artifact_path,
                    'encoding': 'utf-8',
                    'text': text,
                    'lines': text.splitlines(),
                },
            }
            text_path = Path(tmp) / 'trace.log'
            text_path.write_text('line one\nline two\n', encoding='utf-8')
            binary_path = Path(tmp) / 'screen.bin'
            binary_path.write_bytes(b'\x00\x01\x02')
            artifacts.update({
                'trace.log': {
                    'resolved': text_path,
                    'encoding': 'utf-8',
                    'text': text_path.read_text(encoding='utf-8'),
                    'lines': text_path.read_text(
                        encoding='utf-8',
                    ).splitlines(),
                },
                'screen.bin': {
                    'resolved': binary_path,
                    'encoding': 'binary',
                },
            })
            base = {
                'family': 'treatment',
                'code': 'treatment.failed',
                'severity': 'high',
                'evidence_state': 'verified',
                'evaluation_id': 'evaluation',
                'plan_id': 'plan',
                'entry_id': 'entry',
                'case_id': 'case',
                'treatment_id': 'candidate',
                'repeat': 1,
                'attempt': 1,
                'dimension': 'outcome',
                'requirement_id': 'outcome',
                'fault_id': None,
                'gate_id': None,
                'principal_id': None,
                'handoff_id': None,
                'action_id': None,
                'observation_id': None,
                'finding_id': None,
                'reason_key': 'required_outcome_failed',
                'locator': {
                    'kind': 'json_pointer',
                    'artifact': 'evidence.json',
                    'json_pointer': '/value',
                },
                'occurrence_count': 1,
                'observed': 'first prose',
                'expected': 'required outcome passes',
                'impact': 'candidate contribution is blocked',
                'retest': 'rerun the bound entry',
            }
            analyzer = load_analyzer_module()
            first = analyzer._finalize_v5_failures([base, base], artifacts)
            changed = {
                **base,
                'observed': 'different prose',
                'retest': 'different retest prose',
            }
            second = analyzer._finalize_v5_failures([changed], artifacts)
            self.assertEqual(first[0]['failure_id'], second[0]['failure_id'])
            self.assertEqual(2, first[0]['occurrence_count'])
            other = {
                **base,
                'requirement_id': 'second',
                'reason_key': 'second_requirement_failed',
            }
            forward = analyzer._finalize_v5_failures(
                [base, other], artifacts,
            )
            reverse = analyzer._finalize_v5_failures(
                [{**other, 'observed': 'changed'}, changed], artifacts,
            )
            self.assertEqual(
                [item['failure_id'] for item in forward],
                [item['failure_id'] for item in reverse],
            )

            invalid = copy.deepcopy(base)
            invalid['locator']['json_pointer'] = '/missing'
            with self.assertRaisesRegex(ValueError, 'target does not exist'):
                analyzer._finalize_v5_failures([invalid], artifacts)
            for locator in (
                {
                    'kind': 'text_lines',
                    'artifact': 'trace.log',
                    'start_line': 1,
                    'end_line': 2,
                },
                {
                    'kind': 'byte_range',
                    'artifact': 'screen.bin',
                    'start_byte': 0,
                    'end_byte_exclusive': 3,
                },
            ):
                finalized = analyzer._finalize_v5_failures(
                    [{**base, 'locator': locator}], artifacts,
                )
                self.assertEqual(1, len(finalized))
            invalid_range = {
                **base,
                'locator': {
                    'kind': 'byte_range',
                    'artifact': 'screen.bin',
                    'start_byte': 0,
                    'end_byte_exclusive': 4,
                },
            }
            with self.assertRaisesRegex(ValueError, 'out of bounds'):
                analyzer._finalize_v5_failures(
                    [invalid_range], artifacts,
                )

            distinct = {**base, 'requirement_id': 'other'}
            with mock.patch.object(
                analyzer, '_failure_id', return_value='sf-' + 'a' * 24,
            ):
                with self.assertRaisesRegex(ValueError, 'collision'):
                    analyzer._finalize_v5_failures(
                        [base, distinct], artifacts,
                    )

    def test_v5_metric_analysis_clusters_cases_and_preserves_ceiling(self) -> None:
        spec = {
            'level': 'L2',
            'analysis': {
                'estimands': [{
                    'estimand_id': 'task-benefit',
                    'metric': 'task_pass_rate',
                    'candidate_treatment_id': 'candidate',
                    'comparator_treatment_id': 'baseline',
                    'direction': 'higher_is_better',
                    'effect': 'absolute',
                    'minimum_benefit': 0.0,
                    'eligible_modules': ['core_outcome'],
                }],
                'confidence_level': 0.95,
                'bootstrap_iterations': 200,
                'resampling_unit': 'case',
                'slices': [],
                'reliability': ['observed_consistency'],
                'materiality': {'minimum_cases': 3},
            },
            'hard_gates': [],
            'treatments': [
                {'treatment_id': 'baseline', 'causal_role': 'baseline'},
                {'treatment_id': 'candidate', 'causal_role': 'candidate'},
            ],
        }
        plan = {'ordering': {'seed': 7}}
        analyzer = load_analyzer_module()
        supported = analyzer._v5_metric_analysis(
            spec,
            plan,
            material_failure_records({'a', 'b', 'c'}, set()),
            evidence_status='complete',
            feasibility_status='feasible',
        )
        self.assertEqual('supported', supported['usefulness_status'])
        self.assertEqual(4, supported['primary_benefit']['case_count'])

        ceiling = analyzer._v5_metric_analysis(
            spec,
            plan,
            material_failure_records({'a', 'b'}, set()),
            evidence_status='complete',
            feasibility_status='feasible',
        )
        self.assertEqual(
            'inconclusive_ceiling', ceiling['usefulness_status'],
        )
        self.assertEqual(
            'inconclusive_ceiling', ceiling['primary_benefit']['status'],
        )

        negative = analyzer._v5_metric_analysis(
            spec,
            plan,
            material_failure_records({'a', 'b', 'c'}, {'d'}),
            evidence_status='complete',
            feasibility_status='feasible',
        )
        self.assertEqual('not_supported', negative['usefulness_status'])

    def test_v5_safety_protected_module_and_context_gates_do_not_compensate(
        self,
    ) -> None:
        spec = {
            'level': 'L2',
            'analysis': {
                'estimands': [{
                    'estimand_id': 'task-benefit',
                    'metric': 'task_pass_rate',
                    'candidate_treatment_id': 'candidate',
                    'comparator_treatment_id': 'baseline',
                    'direction': 'higher_is_better',
                    'effect': 'absolute',
                    'minimum_benefit': -1.0,
                    'eligible_modules': ['core_outcome'],
                }],
                'confidence_level': 0.95,
                'bootstrap_iterations': 100,
                'materiality': {'minimum_cases': 0},
            },
            'hard_gates': [
                {
                    'gate_id': 'safety',
                    'kind': 'safety',
                    'metric': 'critical_safety_incidents',
                    'direction': 'at_most',
                    'threshold': 0,
                    'authority': 'safety-owner',
                    'required': True,
                },
                {
                    'gate_id': 'protected',
                    'kind': 'protected',
                    'metric': 'protected_outcome_failures',
                    'direction': 'equal',
                    'threshold': 0,
                    'authority': 'outcome-owner',
                    'required': True,
                },
                {
                    'gate_id': 'module',
                    'kind': 'module',
                    'metric': 'core_outcome_pass_rate',
                    'direction': 'at_least',
                    'threshold': 1.0,
                    'authority': 'module-owner',
                    'required': True,
                },
                {
                    'gate_id': 'context',
                    'kind': 'context',
                    'metric': 'skill_context_attribution_rate',
                    'direction': 'at_least',
                    'threshold': 1.0,
                    'authority': 'context-owner',
                    'required': True,
                },
            ],
        }
        entries = []
        records = []
        for case_id in ('a', 'b'):
            for treatment in ('baseline', 'candidate'):
                entry_id = f'{case_id}-{treatment}'
                failed = case_id == 'b' and treatment == 'candidate'
                entries.append({
                    'entry_id': entry_id,
                    'disposition': 'execute',
                    'execute_case_payload': {
                        'case': {
                            'tags': ['protected'],
                            'requirements': [{
                                'requirement_id': 'outcome',
                                'required': True,
                                'dimension': 'outcome',
                            }],
                        },
                    },
                })
                records.append({
                    'entry_id': entry_id,
                    'case_id': case_id,
                    'variant': treatment,
                    'repeat': 1,
                    'valid': True,
                    'task_pass': not failed,
                    'safety_pass': not failed,
                    'hard_gate_failures': ['outcome'] if failed else [],
                    'critical_safety_incidents': 1 if failed else 0,
                    'unauthorized_side_effects': 0,
                })
        analysis = load_analyzer_module()._v5_metric_analysis(
            spec,
            {'entries': entries, 'ordering': {'seed': 7}},
            records,
            evidence_status='complete',
            feasibility_status='feasible',
            module_summaries=[{
                'module': 'core_outcome',
                'status': 'pass',
                'pass_rate': 1.0,
                'lower': 1.0,
                'upper': 1.0,
            }],
            context_cost={'attribution_coverage': 1.0},
        )
        statuses = {
            item['gate']['gate_id']: (item['status'], item['observed'])
            for item in analysis['gate_results']
        }
        self.assertEqual(('fail', 1), statuses['safety'])
        self.assertEqual(('fail', 1), statuses['protected'])
        self.assertEqual(('pass', 1.0), statuses['module'])
        self.assertEqual(('pass', 1.0), statuses['context'])
        self.assertEqual('not_supported', analysis['usefulness_status'])

    def test_v5_context_pairs_keep_task_failures_but_require_attribution(self) -> None:
        spec = {
            'analysis': {
                'estimands': [{
                    'candidate_treatment_id': 'candidate',
                    'comparator_treatment_id': 'baseline',
                }],
                'confidence_level': 0.95,
                'bootstrap_iterations': 100,
            },
        }
        plan = {'ordering': {'seed': 7}}
        records = []
        for case_id in ('a', 'b'):
            for variant, context_bytes in (
                ('baseline', 100),
                ('candidate', 50),
            ):
                records.append({
                    'run_id': f'{case_id}-{variant}',
                    'variant': variant,
                    'case_id': case_id,
                    'repeat': 1,
                    'valid': True,
                    'task_pass': not (
                        variant == 'candidate' and case_id == 'a'
                    ),
                    'context_usage': {
                        'attributed': True,
                        'bytes': context_bytes,
                        'controlled_bytes': context_bytes,
                        'controlled_core_bytes': context_bytes,
                    },
                    'tokens_in': 1,
                    'tokens_out': 1,
                    'latency_ms': 1,
                    'tool_calls': 1,
                    'retries': 0,
                    'pricing_identity': 'fixture-pricing',
                    'usage_records': [{
                        'principal_id': f'principal-{variant}',
                        'turn_id': 'turn-1',
                        'phase': 'execute',
                        'call_id': 'call-1',
                        'input_tokens': 1,
                        'output_tokens': 1,
                        'cache_read_tokens': 0,
                        'cache_write_tokens': 0,
                        'queue_ms': 0,
                        'runtime_ms': 1,
                        'tool_calls': 1,
                        'retries': 0,
                        'rework': 0,
                        'network_calls': 0,
                        'residue_count': 0,
                        'requested_effort': 1,
                        'effective_effort': 1,
                    }],
                    'counts': {'workflow_artifact_count': 1},
                })
        analyzer = load_analyzer_module()
        complete = analyzer._v5_context_cost(spec, plan, records)
        self.assertEqual(1.0, complete['attribution_coverage'])
        self.assertEqual(
            2, complete['skill_context_bytes']['case_count'],
        )
        self.assertEqual('pass', complete['skill_context_bytes']['status'])
        self.assertEqual(0, complete['tokens']['metrics']['cache_read'])
        self.assertEqual(2, complete['calls']['metrics']['principal_count'])
        self.assertEqual(1, complete['calls']['metrics']['turn_count'])
        self.assertEqual(1, complete['calls']['metrics']['phase_count'])
        self.assertEqual(4, complete['calls']['metrics']['call_count'])
        self.assertEqual(
            'not_applicable', complete['failure_recovery_overhead']['status'],
        )
        self.assertEqual('pass', complete['cache']['status'])

        records[0]['context_usage']['attributed'] = False
        incomplete = analyzer._v5_context_cost(spec, plan, records)
        self.assertEqual(0.75, incomplete['attribution_coverage'])
        self.assertEqual(
            'not_evaluable', incomplete['skill_context_bytes']['status'],
        )

    def test_v5_l2_cli_distinguishes_ceiling_support_and_negative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_analysis_bundle(
                root, level='L2', case_count=3,
            )

            def analyze(stem: str) -> tuple[subprocess.CompletedProcess[str], dict]:
                result = self.call_cli(
                    'scripts/analyze_runs.py',
                    str(paths['index']),
                    '--spec', str(paths['spec']),
                    '--json', str(root / f'{stem}-summary.json'),
                    '--failure-index', str(root / f'{stem}-failures.json'),
                )
                summary = json.loads(
                    (root / f'{stem}-summary.json').read_text(encoding='utf-8'),
                )
                return result, summary

            ceiling_result, ceiling = analyze('ceiling')
            self.assertEqual(
                3, ceiling_result.returncode,
                ceiling_result.stdout + ceiling_result.stderr,
            )
            self.assertEqual('inconclusive_ceiling', ceiling['usefulness_status'])
            self.assertEqual(3, ceiling['primary_benefit']['case_count'])

            baseline_failures = {
                ('baseline', f'case-{index}') for index in range(1, 4)
            }
            self._rewrite_v5_outcomes(paths, baseline_failures)
            supported_result, supported = analyze('supported')
            self.assertEqual(
                0, supported_result.returncode,
                supported_result.stdout + supported_result.stderr,
            )
            self.assertEqual('supported', supported['usefulness_status'])

            self._rewrite_v5_outcomes(
                paths, {('candidate', 'case-1')},
            )
            negative_result, negative = analyze('negative')
            self.assertEqual(
                1, negative_result.returncode,
                negative_result.stdout + negative_result.stderr,
            )
            self.assertEqual('not_supported', negative['usefulness_status'])
            negative_failures = json.loads(
                (root / 'negative-failures.json').read_text(encoding='utf-8'),
            )
            self.assertIn(
                'treatment.failed',
                {item['code'] for item in negative_failures['failures']},
            )

    def test_v5_exit_precedence_and_report_only_override(self) -> None:
        analyzer = load_analyzer_module()
        summary = {
            'analysis_ready': True,
            'evidence_status': 'complete',
            'usefulness_status': 'not_supported',
            'final_authority_status': 'blocked',
            'manual_authority': {
                'required': False,
                'status': 'not_applicable',
                'decision': None,
                'receipt_hash': None,
            },
        }
        self.assertEqual(1, analyzer._v5_base_exit('L2', summary))
        self.assertEqual(
            0, analyzer._v5_exit_code('L2', summary, report_only=True),
        )
        for evidence_status, usefulness in (
            ('incomplete', 'not_evaluable'),
            ('invalid', 'not_evaluable'),
            ('complete', 'not_evaluable'),
            ('complete', 'inconclusive_ceiling'),
        ):
            blocked = {
                **summary,
                'evidence_status': evidence_status,
                'usefulness_status': usefulness,
            }
            self.assertEqual(
                3,
                analyzer._v5_exit_code(
                    'L2', blocked, report_only=True,
                ),
            )
        diagnostic = {
            **summary,
            'usefulness_status': 'not_evaluable',
            'final_authority_status': 'eligible',
        }
        self.assertEqual(0, analyzer._v5_base_exit('L1', diagnostic))

    def test_v5_manual_authority_missing_approve_hold_and_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_analysis_bundle(
                root, manual_required=True,
            )
            artifacts = root / 'artifacts'
            review_root = artifacts / 'manual'
            review_root.mkdir()
            evidence_path = review_root / 'outcome.txt'
            evidence_path.write_text('reviewed outcome\n', encoding='utf-8')
            evidence = {
                'type': 'outcome-review',
                'artifact': 'manual/outcome.txt',
                'sha256': (
                    'sha256:'
                    + hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                ),
            }

            def write_receipt(
                name: str,
                decision: str,
                signature: str = 'attested',
            ) -> str:
                receipt_path = review_root / f'{name}.json'
                receipt_path.write_text(json.dumps({
                    'reviewer_role': 'independent-evaluator',
                    'evidence': [evidence],
                    'decision': decision,
                    'signature': signature,
                }), encoding='utf-8')
                return f'manual/{name}.json'

            def analyze(
                stem: str,
                receipt: str | None,
                *,
                report_only: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                args = [
                    'scripts/analyze_runs.py',
                    str(paths['index']),
                    '--spec', str(paths['spec']),
                    '--json', str(root / f'{stem}-summary.json'),
                    '--failure-index', str(root / f'{stem}-failures.json'),
                ]
                if receipt is not None:
                    args.extend(['--manual-review-receipt', receipt])
                if report_only:
                    args.append('--report-only')
                return self.call_cli(*args)

            missing = analyze('missing', None)
            self.assertEqual(3, missing.returncode, missing.stdout + missing.stderr)
            missing_summary = json.loads(
                (root / 'missing-summary.json').read_text(encoding='utf-8'),
            )
            self.assertEqual('missing', missing_summary['manual_authority']['status'])

            approved = analyze('approved', write_receipt('approved', 'approve'))
            self.assertEqual(0, approved.returncode, approved.stdout + approved.stderr)
            approved_summary = json.loads(
                (root / 'approved-summary.json').read_text(encoding='utf-8'),
            )
            self.assertEqual('eligible', approved_summary['final_authority_status'])
            self.assertEqual('approve', approved_summary['manual_authority']['decision'])

            hold_receipt = write_receipt('hold', 'hold')
            held = analyze('held', hold_receipt)
            self.assertEqual(1, held.returncode, held.stdout + held.stderr)
            report_only = analyze(
                'held-report', hold_receipt, report_only=True,
            )
            self.assertEqual(
                0, report_only.returncode,
                report_only.stdout + report_only.stderr,
            )

            invalid = analyze(
                'invalid',
                write_receipt('invalid', 'approve', signature='   '),
                report_only=True,
            )
            self.assertEqual(3, invalid.returncode, invalid.stdout + invalid.stderr)
            invalid_summary = json.loads(
                (root / 'invalid-summary.json').read_text(encoding='utf-8'),
            )
            self.assertEqual('invalid', invalid_summary['manual_authority']['status'])

    def test_v5_report_transaction_truncation_and_immutable_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_analysis_bundle(
                root, failure_index_budget=1,
            )
            paths['index'].write_text('', encoding='utf-8')
            command = (
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
                '--markdown', str(paths['markdown']),
            )
            first = self.call_cli(*command)
            self.assertEqual(3, first.returncode, first.stdout + first.stderr)
            summary_bytes = paths['summary'].read_bytes()
            first_again = self.call_cli(*command)
            self.assertEqual(
                3, first_again.returncode,
                first_again.stdout + first_again.stderr,
            )
            self.assertEqual(summary_bytes, paths['summary'].read_bytes())

            summary = json.loads(summary_bytes)
            compact = json.loads(paths['failures'].read_text(encoding='utf-8'))
            details_view = summary['output_manifest']['details']
            details_path = root / details_view['path']
            details = json.loads(details_path.read_text(encoding='utf-8'))
            self.assertTrue(compact['truncated'])
            self.assertEqual((2, 1, 1), (
                compact['item_count'],
                compact['shown_count'],
                compact['omitted_count'],
            ))
            self.assertEqual((2, 2, 0, False), (
                details['item_count'],
                details['shown_count'],
                details['omitted_count'],
                details['truncated'],
            ))
            self.assertEqual(
                'sha256:' + hashlib.sha256(details_path.read_bytes()).hexdigest(),
                details_view['sha256'],
            )

    def test_v5_report_preflight_never_writes_false_complete_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_analysis_bundle(root)
            paths['markdown'].write_text('conflicting bytes\n', encoding='utf-8')
            result = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
                '--markdown', str(paths['markdown']),
            )
            self.assertEqual(2, result.returncode, result.stdout + result.stderr)
            self.assertFalse(paths['summary'].exists())
            self.assertFalse(paths['failures'].exists())
            self.assertEqual(
                'conflicting bytes\n',
                paths['markdown'].read_text(encoding='utf-8'),
            )

    def test_v5_active_surface_summaries_are_evidence_bound(self) -> None:
        fixtures = (
            (
                materialize_v5_handoff_fixture,
                'multi_principal_coordination',
                'coordination_summary',
            ),
            (
                materialize_v5_action_fixture,
                None,
                'action_summary',
            ),
            (
                materialize_v5_fault_fixture,
                'tool_faults',
                'action_summary',
            ),
            (
                materialize_v5_observation_fixture,
                None,
                'grounding_summary',
            ),
        )
        for materializer, module, summary_key in fixtures:
            with self.subTest(summary=summary_key), tempfile.TemporaryDirectory() as tmp:
                summary = self._run_v5_fixture_analysis(
                    Path(tmp), materializer,
                )
                self.assertEqual('pass', summary[summary_key]['status'])
                if module is not None:
                    module_summary = next(
                        item for item in summary['module_summaries']
                        if item['module'] == module
                    )
                    self.assertEqual('pass', module_summary['status'])
                active_surfaces = {
                    item['surface'] for item in summary['stage_summaries']
                }
                if summary_key == 'action_summary':
                    self.assertIn('action_effect', active_surfaces)
                if summary_key == 'grounding_summary':
                    self.assertIn('grounding', active_surfaces)

    def test_material_failure_is_aggregated_by_case_not_repeat(self) -> None:
        summary = load_analyzer_module().summarize_material_failure_cases(
            material_failure_records({"a", "b", "c"}, {"c"}),
            baseline="baseline",
            candidate="candidate",
            case_ids={"a", "b", "c", "d"},
            repeats=2,
            material_failure_ids={"material-contract"},
        )
        self.assertEqual(3, summary["baseline_material_failure_cases"])
        self.assertEqual(1, summary["candidate_material_failure_cases"])
        self.assertEqual(2, summary["resolved_baseline_failure_cases"])
        self.assertEqual("supported", summary["usefulness_status"])

    def test_candidate_only_material_failure_blocks_support(self) -> None:
        summary = load_analyzer_module().summarize_material_failure_cases(
            material_failure_records({"a", "b", "c"}, {"c", "d"}),
            baseline="baseline",
            candidate="candidate",
            case_ids={"a", "b", "c", "d"},
            repeats=2,
            material_failure_ids={"material-contract"},
        )
        self.assertEqual(1, summary["candidate_only_failure_cases"])
        self.assertEqual("not_supported", summary["usefulness_status"])

    def test_baseline_ceiling_returns_inconclusive(self) -> None:
        summary = load_analyzer_module().summarize_material_failure_cases(
            material_failure_records({"a", "b"}, set()),
            baseline="baseline",
            candidate="candidate",
            case_ids={"a", "b", "c", "d"},
            repeats=2,
            material_failure_ids={"material-contract"},
        )
        self.assertTrue(summary["evidence_complete"])
        self.assertEqual("inconclusive_ceiling", summary["usefulness_status"])

    def test_matched_planner_executor_tokens_require_every_repeat(self) -> None:
        planner = []
        executor = []
        arm_map = {}
        for case_id in ("a", "b"):
            for repeat in (1, 2):
                for planner_variant, executor_variant, tokens in (
                    ("baseline", "executor_baseline", 100),
                    ("candidate_explicit", "executor_candidate", 70),
                ):
                    planner.append({
                        "variant": planner_variant,
                        "case_id": case_id,
                        "repeat": repeat,
                        "valid": True,
                        "task_pass": True,
                        "tokens_in": tokens,
                        "tokens_out": 0,
                    })
                    transfer_case = (
                        f"{case_id}-{repeat}-{executor_variant}"
                    )
                    arm_map[transfer_case] = {
                        "source_case_id": case_id,
                        "planner_repeat": repeat,
                    }
                    executor.append({
                        "variant": executor_variant,
                        "case_id": transfer_case,
                        "repeat": 1,
                        "valid": True,
                        "task_pass": True,
                        "tokens_in": tokens,
                        "tokens_out": 0,
                    })
        analyzer = load_analyzer_module()
        complete = analyzer.matched_planner_executor_tokens(
            planner,
            executor,
            arm_map,
            baseline_planner="baseline",
            candidate_planner="candidate_explicit",
            baseline_executor="executor_baseline",
            candidate_executor="executor_candidate",
            case_ids={"a", "b"},
            repeats=2,
        )
        self.assertTrue(complete["complete"])
        self.assertEqual("complete", complete["status"])
        self.assertEqual(2, complete["case_count"])
        self.assertAlmostEqual(0.30, complete["point"])
        self.assertAlmostEqual(0.30, complete["lower"])
        self.assertAlmostEqual(0.30, complete["upper"])

        planner.append(dict(planner[0]))
        duplicate = analyzer.matched_planner_executor_tokens(
            planner,
            executor,
            arm_map,
            baseline_planner="baseline",
            candidate_planner="candidate_explicit",
            baseline_executor="executor_baseline",
            candidate_executor="executor_candidate",
            case_ids={"a", "b"},
            repeats=2,
        )
        self.assertFalse(duplicate["complete"])
        self.assertTrue(duplicate["duplicate_planner_keys"])
        planner.pop()

        planner[0]["tokens_in"] = True
        invalid_tokens = analyzer.matched_planner_executor_tokens(
            planner,
            executor,
            arm_map,
            baseline_planner="baseline",
            candidate_planner="candidate_explicit",
            baseline_executor="executor_baseline",
            candidate_executor="executor_candidate",
            case_ids={"a", "b"},
            repeats=2,
        )
        self.assertFalse(invalid_tokens["complete"])
        self.assertEqual("invalid_tokens", invalid_tokens["excluded_pairs"][0]["reason"])
        planner[0]["tokens_in"] = 100

        executor.pop()
        incomplete = analyzer.matched_planner_executor_tokens(
            planner,
            executor,
            arm_map,
            baseline_planner="baseline",
            candidate_planner="candidate_explicit",
            baseline_executor="executor_baseline",
            candidate_executor="executor_candidate",
            case_ids={"a", "b"},
            repeats=2,
        )
        self.assertFalse(incomplete["complete"])
        self.assertEqual("incomplete", incomplete["status"])
        self.assertEqual(1, incomplete["case_count"])

    def test_host_preflight_bytes_are_separate_from_executor_prewrite(self) -> None:
        analyzer = load_analyzer_module()
        record = {
            "bytes": {
                "host_preflight_tool_output_bytes": 900,
                "executor_prewrite_tool_output_bytes": 120,
            },
            "context_usage": {
                "controlled_bytes": 345,
                "controlled_core_bytes": 123,
            },
            "counts": {"executor_prewrite_task_tool_calls": 2},
        }
        self.assertEqual(
            (900.0, 900.0),
            analyzer.paired_metric_value(record, "host_preflight_tool_output_bytes"),
        )
        self.assertEqual(
            (123.0, 123.0),
            analyzer.paired_metric_value(
                record, "controlled_core_skill_context_bytes",
            ),
        )
        self.assertEqual(
            (120.0, 120.0),
            analyzer.paired_metric_value(
                record, "executor_prewrite_tool_output_bytes"
            ),
        )
        self.assertEqual(
            (2.0, 2.0),
            analyzer.paired_metric_value(
                record, "executor_prewrite_task_tool_calls"
            ),
        )
        self.assertEqual(
            (345.0, 345.0),
            analyzer.paired_metric_value(
                record, "controlled_skill_context_bytes"
            ),
        )

    def test_negative_lift_cannot_report_usefulness_supported_when_absolute_rate_passes(self) -> None:
        analyzer = load_analyzer_module()
        benefit = analyzer.evaluate_benefit(
            {'status': 'complete', 'point': -0.2, 'lower': -0.3, 'upper': -0.1},
            0.1,
        )
        self.assertEqual(benefit['status'], 'fail')
        status = analyzer.derive_usefulness_status(
            level='L2', evidence_status='complete', primary_benefit_status=benefit['status'],
            guardrail_statuses=['pass', 'pass'], protected_outcome_failures=0,
            material_harm=False, candidate_hard_failures=0,
        )
        self.assertEqual(status, 'not_supported')

    def test_evidence_and_usefulness_cover_five_declared_states(self) -> None:
        analyzer = load_analyzer_module()
        scenarios = {
            'supported': ('complete', 'pass', ['pass'], 'supported'),
            'not_supported': ('complete', 'fail', ['pass'], 'not_supported'),
            'not_evaluable': ('complete', 'not_evaluable', ['pass'], 'not_evaluable'),
            'incomplete': ('incomplete', 'pass', ['pass'], 'not_evaluable'),
            'invalid': ('invalid', 'pass', ['pass'], 'not_evaluable'),
        }
        observed = {}
        for name, (evidence, benefit, guardrails, expected_usefulness) in scenarios.items():
            usefulness = analyzer.derive_usefulness_status(
                level='L2', evidence_status=evidence, primary_benefit_status=benefit,
                guardrail_statuses=guardrails, protected_outcome_failures=0,
                material_harm=False, candidate_hard_failures=0,
            )
            observed[name] = {'evidence_status': evidence, 'usefulness_status': usefulness}
            self.assertEqual(expected_usefulness, usefulness)
        self.assertEqual(
            {'supported', 'not_supported', 'not_evaluable', 'incomplete', 'invalid'},
            set(observed),
        )
        self.assertEqual('invalid', analyzer.derive_evidence_status(
            current_status='complete', incomplete_matrix=True,
            duplicate_pairs=False, identity_invalid=True,
        ))


    def test_paired_metric_summary_normalizes_scores_and_preserves_case_ids(self) -> None:
        analyzer = load_analyzer_module()
        records = []
        for case_id, baseline_score, candidate_score in (
            ('case-a', 50, 70), ('case-b', 80, 90),
        ):
            for repeat in (1, 2):
                records.extend([
                    {'case_id': case_id, 'repeat': repeat, 'variant': 'baseline',
                     'valid': True, 'task_pass': True, 'quality_score': baseline_score},
                    {'case_id': case_id, 'repeat': repeat, 'variant': 'candidate',
                     'valid': True, 'task_pass': True, 'quality_score': candidate_score},
                ])
        summary = analyzer.summarize_paired_metric(
            records, comparator='baseline', candidate='candidate',
            metric='quality_score_normalized', direction='higher_is_better',
            effect='absolute', confidence_level=0.95,
            bootstrap_iterations=200, random_seed=7,
        )
        self.assertEqual('complete', summary['status'])
        self.assertEqual((2, 2), (summary['case_count'], summary['repeat_count']))
        self.assertAlmostEqual(0.15, summary['point'])
        self.assertEqual(['case-a', 'case-b'], [row['case_id'] for row in summary['case_differences']])
        self.assertEqual('normalized_0_1', summary['scale']['reported'])
        self.assertEqual(50.0, summary['case_differences'][0]['comparator_raw_value'])
        self.assertEqual(0.5, summary['case_differences'][0]['comparator_value'])
        self.assertEqual(
            'higher_is_better:absolute:quality_score_normalized:candidate_vs_baseline',
            summary['estimand'],
        )


    def test_report_paired_metric_map_uses_primary_and_guardrail_contracts(self) -> None:
        analyzer = load_analyzer_module()
        spec = make_minimal_spec('L2')
        spec['analysis']['primary_benefit'] = {
            'metric': 'quality_score_normalized', 'comparator': 'baseline',
            'direction': 'higher_is_better', 'effect': 'absolute', 'minimum_benefit': 0.05,
        }
        spec['metrics'] = ['quality_score_normalized', 'task_pass_rate']
        spec['hard_gates'].append({
            'id': 'task-ni', 'metric': 'task_pass_rate', 'comparator': 'baseline',
            'direction': 'higher_is_better', 'effect': 'absolute', 'minimum_benefit': -0.05,
        })
        cases = {
            case_id: {
                'attribution_evaluable': True,
                'applicable_variant_profiles': ['baseline/skill_disabled', 'candidate/natural_routing'],
            }
            for case_id in ('case-a', 'case-b')
        }
        records = []
        for case_id in cases:
            records.extend([
                {'case_id': case_id, 'repeat': 1, 'variant': 'baseline',
                 'valid': True, 'task_pass': True, 'quality_score': 70},
                {'case_id': case_id, 'repeat': 1, 'variant': 'candidate_natural',
                 'valid': True, 'task_pass': True, 'quality_score': 80},
            ])
        metrics, failures = analyzer.build_paired_metrics(
            records, spec, candidate='candidate_natural',
            comparator_variants={'baseline': 'baseline', 'prior': None},
            cases_by_id=cases,
        )
        self.assertEqual({'quality_score_normalized', 'task_pass_rate'}, set(metrics))
        self.assertEqual([], failures)
        self.assertEqual(('baseline', 'baseline'), (
            metrics['quality_score_normalized']['comparator'],
            metrics['quality_score_normalized']['comparator_variant'],
        ))
        self.assertEqual('pass', analyzer.evaluate_benefit(
            metrics['quality_score_normalized'], 0.05,
        )['status'])


    def test_relative_cost_benefit_direction_and_zero_denominator(self) -> None:
        analyzer = load_analyzer_module()
        records = []
        for case_id, baseline_tokens, candidate_tokens, candidate_pass in (
            ('case-a', 100, 80, True),
            ('case-b', 200, 150, True),
            ('early-failure', 300, 1, False),
        ):
            records.extend([
                {'case_id': case_id, 'repeat': 1, 'variant': 'baseline',
                 'valid': True, 'task_pass': True, 'tokens_in': baseline_tokens},
                {'case_id': case_id, 'repeat': 1, 'variant': 'candidate',
                 'valid': True, 'task_pass': candidate_pass, 'tokens_in': candidate_tokens},
            ])
        summary = analyzer.summarize_paired_metric(
            records, comparator='baseline', candidate='candidate', metric='tokens_in',
            direction='lower_is_better', effect='absolute', confidence_level=0.95,
            bootstrap_iterations=200, random_seed=11,
        )
        self.assertEqual('complete', summary['status'])
        self.assertAlmostEqual(35.0, summary['point'])
        self.assertEqual(['early-failure'], [row['case_id'] for row in summary['task_failures']])

        relative = analyzer.summarize_paired_metric(
            records, comparator='baseline', candidate='candidate', metric='tokens_in',
            direction='lower_is_better', effect='relative', confidence_level=0.95,
            bootstrap_iterations=200, random_seed=11,
        )
        self.assertEqual('complete', relative['status'])
        self.assertAlmostEqual(0.225, relative['point'])

        for row in records:
            if row['case_id'] == 'case-a' and row['variant'] == 'baseline':
                row['tokens_in'] = 0
        relative = analyzer.summarize_paired_metric(
            records, comparator='baseline', candidate='candidate', metric='tokens_in',
            direction='lower_is_better', effect='relative', confidence_level=0.95,
            bootstrap_iterations=200, random_seed=11,
        )
        self.assertEqual('complete', relative['status'])
        self.assertAlmostEqual(-0.375, relative['point'])
        for row in records:
            if row['case_id'] == 'case-a' and row['variant'] == 'candidate':
                row['tokens_in'] = 0
        no_cost = analyzer.summarize_paired_metric(
            records, comparator='baseline', candidate='candidate', metric='tokens_in',
            direction='lower_is_better', effect='relative', confidence_level=0.95,
            bootstrap_iterations=200, random_seed=11,
        )
        self.assertAlmostEqual(0.125, no_cost['point'])

    def test_prewrite_uses_absolute_delta_upper_bound(self) -> None:
        analyzer = load_analyzer_module()
        records = []
        for case_id, baseline, candidate in (
            ('case-a', 100, 120),
            ('case-b', 200, 190),
        ):
            records.extend([
                {
                    'case_id': case_id, 'repeat': 1, 'variant': 'baseline',
                    'valid': True, 'task_pass': True,
                    'bytes': {'executor_prewrite_tool_output_bytes': baseline},
                },
                {
                    'case_id': case_id, 'repeat': 1, 'variant': 'candidate',
                    'valid': True, 'task_pass': True,
                    'bytes': {'executor_prewrite_tool_output_bytes': candidate},
                },
            ])
        summary = analyzer.summarize_paired_cost_delta(
            records,
            comparator='baseline',
            candidate='candidate',
            metric='executor_prewrite_tool_output_bytes',
            confidence_level=0.95,
            bootstrap_iterations=500,
            random_seed=17,
        )
        self.assertEqual('complete', summary['status'])
        self.assertAlmostEqual(5.0, summary['point'])
        self.assertAlmostEqual(20.0, summary['upper'])
        self.assertEqual(
            [20.0, -10.0],
            [row['delta'] for row in summary['case_differences']],
        )


    def test_routing_aggregates_repeats_by_case_and_reports_disagreement(self) -> None:
        analyzer = load_analyzer_module()
        rows = []
        patterns = {
            'positive-consistent': (True, [True, True]),
            'positive-disagreement': (True, [True, False]),
            'negative-consistent': (False, [False, False]),
            'negative-disagreement': (False, [False, True]),
        }
        for case_id, (should_trigger, body_loads) in patterns.items():
            for repeat, body_loaded in enumerate(body_loads, 1):
                rows.append({
                    'run_id': f'{case_id}:{repeat}', 'case_id': case_id, 'repeat': repeat,
                    'valid': True, 'routing_evaluable': True, 'should_trigger': should_trigger,
                    'retrieved_skill_ids': ['example-skill'] if body_loaded else [],
                    'selected_skill_id': 'example-skill' if body_loaded else None,
                    'skill_body_loaded': body_loaded, 'resources_loaded': [],
                    'skill_incorporated': body_loaded, 'skill_applied': body_loaded,
                })
        routing = analyzer.routing_summary(rows, 'example-skill')
        self.assertEqual('complete', routing['status'])
        self.assertEqual(4, routing['n'])
        self.assertEqual({'tp': 1, 'fp': 1, 'tn': 1, 'fn': 1}, routing['confusion'])
        self.assertEqual(0.5, routing['repeat_consistency']['rate'])
        self.assertEqual(4, routing['repeat_consistency']['n'])
        self.assertEqual(analyzer.wilson(1, 2), routing['recall_wilson95'])


    def test_context_summary_conserves_all_valid_runs_and_accounts_negative_false_loads(self) -> None:
        analyzer = load_analyzer_module()
        spec = make_minimal_spec('L2')
        cases = {
            'positive': {'should_trigger': True, 'attribution_evaluable': True,
                         'applicable_variant_profiles': ['candidate/natural_routing']},
            'negative-clean': {'should_trigger': False, 'attribution_evaluable': False,
                               'applicable_variant_profiles': ['candidate/natural_routing']},
            'negative-disagreement': {'should_trigger': False, 'attribution_evaluable': False,
                                      'applicable_variant_profiles': ['candidate/natural_routing']},
        }
        records = []
        for case_id, body_loads in (
            ('positive', [True, True]),
            ('negative-clean', [False, False]),
            ('negative-disagreement', [False, True]),
        ):
            for repeat, loaded in enumerate(body_loads, 1):
                body_bytes = 100 if loaded else 0
                records.append({
                    'case_id': case_id, 'repeat': repeat, 'variant': 'candidate_natural',
                    'valid': True, 'skill_body_loaded': loaded,
                    'context_usage': {
                        'attributed': True, 'measurement_source': 'host_receipt',
                        'bytes': body_bytes, 'tokens': body_bytes // 4,
                        'unique_static_content_bytes': body_bytes,
                        'repeated_static_content_bytes': 0,
                        'protocol_output_bytes': 0, 'failed_command_output_bytes': 0,
                        'host_integration_duplicate_bytes': 0,
                        'unexplained_repeated_static_content_bytes': 0,
                        'unattributed_model_body_read_count': 0,
                        'controlled_bytes': body_bytes,
                        'unique_reference_bytes': 0,
                        'controlled_core_bytes': body_bytes,
                        'components': ([{'kind': 'body', 'bytes': body_bytes, 'tokens': body_bytes // 4}]
                                       if loaded else []),
                    },
                })
        summary = analyzer.summarize_skill_context(records, cases, spec, 2)
        self.assertEqual(6, summary['all_valid_rows'])
        self.assertEqual(0, summary['conservation_failures'])
        negative = summary['negative_cohort']
        self.assertEqual(100, negative['false_body_load_bytes'])
        self.assertEqual(1, negative['false_body_load_case_count'])
        self.assertEqual(0.5, negative['false_body_load_rate']['rate'])
        self.assertEqual(analyzer.wilson(1, 2), negative['false_body_load_rate']['wilson95'])
        self.assertEqual(0.5, negative['repeat_consistency']['rate'])


    def test_bootstrap_resamples_cases_not_repeats(self) -> None:
        analyzer = load_analyzer_module()
        records = []
        for case_id in ('case-a', 'case-b'):
            for repeat in range(1, 11):
                for variant, task_pass in (('baseline', False), ('candidate', True)):
                    records.append({
                        'case_id': case_id, 'repeat': repeat, 'variant': variant,
                        'valid': True, 'task_pass': task_pass,
                    })
        summary = analyzer.summarize_paired_metric(
            records, comparator='baseline', candidate='candidate', metric='task_pass_rate',
            direction='higher_is_better', effect='absolute', confidence_level=0.95,
            bootstrap_iterations=500, random_seed=7,
        )
        self.assertEqual(summary['case_count'], 2)
        self.assertEqual(summary['repeat_count'], 10)
        self.assertEqual(['case-a', 'case-b'], [row['case_id'] for row in summary['case_differences']])


    def test_summarize_case_differences_is_permutation_invariant(self) -> None:
        analyzer = load_analyzer_module()
        values = [-1.0, 0.0, 0.25, 0.5, 1.0, 1.0, 1.0, 1.0]
        kwargs = dict(confidence_level=0.95, bootstrap_iterations=500, random_seed=13)
        self.assertEqual(
            analyzer.summarize_case_differences(values, **kwargs),
            analyzer.summarize_case_differences(list(reversed(values)), **kwargs),
        )


    def test_case_bootstrap_extreme_vectors_bound_declared_benefit_gate(self) -> None:
        analyzer = load_analyzer_module()
        kwargs = dict(confidence_level=0.95, bootstrap_iterations=500, random_seed=17)
        no_effect = analyzer.summarize_case_differences([0.0] * 8, **kwargs)
        clear_effect = analyzer.summarize_case_differences([1.0] * 8, **kwargs)
        self.assertEqual(no_effect['case_count'], 8)
        self.assertLess(no_effect['lower'], 0.10)
        self.assertGreaterEqual(clear_effect['lower'], 0.10)


    def test_point_estimate_crossing_without_lower_bound_is_inconclusive(self) -> None:
        analyzer = load_analyzer_module()
        summary = analyzer.summarize_case_differences(
            [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            confidence_level=0.95, bootstrap_iterations=1000, random_seed=19,
        )
        self.assertGreater(summary['point'], 0.10)
        self.assertLess(summary['lower'], 0.10)
        benefit = analyzer.evaluate_benefit({'status': 'complete', **summary}, 0.10)
        self.assertEqual(benefit['status'], 'not_evaluable')
        self.assertEqual(
            analyzer.derive_usefulness_status(
                level='L2', evidence_status='complete', primary_benefit_status=benefit['status'],
                guardrail_statuses=['pass'], protected_outcome_failures=0,
                material_harm=False, candidate_hard_failures=0,
            ),
            'not_evaluable',
        )


    def test_protected_outcome_failures_counts_missing_invalid_and_failed_arm_repeat_rows(self) -> None:
        analyzer = load_analyzer_module()
        cases = {
            'protected-control': {
                'tags': ['protected'],
                'requirements': [{
                    'id': 'required-outcome', 'dimension': 'outcome', 'required': True,
                    'grader_id': 'g', 'check_id': 'outcome',
                }],
            },
        }
        records = [
            {'case_id': 'protected-control', 'variant': 'baseline', 'repeat': 1, 'valid': True, 'hard_gate_failures': []},
            {'case_id': 'protected-control', 'variant': 'candidate', 'repeat': 1, 'valid': False, 'hard_gate_failures': []},
            {'case_id': 'protected-control', 'variant': 'candidate', 'repeat': 2, 'valid': True, 'hard_gate_failures': ['required-outcome']},
        ]
        self.assertEqual(
            analyzer.derive_protected_outcome_failures(
                records, cases, baseline='baseline', candidate='candidate', repeats=2,
            ),
            3,
        )


    def test_context_efficiency_classifies_repeated_and_dynamic_output_bytes(self) -> None:
        def component(
            kind: str,
            source_path: str,
            size: int,
            occurrence: int,
            digit: str,
        ) -> dict:
            return {
                'kind': kind,
                'source_path': source_path,
                'content_sha256': 'sha256:' + digit * 64,
                'bytes': size,
                'occurrence': occurrence,
            }

        context = {
            'status': 'captured',
            'bytes': 48,
            'tokens': None,
            'controlled_bytes': 38,
            'unique_reference_bytes': 8,
            'controlled_core_bytes': 30,
            'components': [
                component('body', 'SKILL.md', 10, 1, '1'),
                component('body', 'SKILL.md', 10, 2, '1'),
                component('protocol_output', 'protocol:helper:1', 7, 1, '2'),
                component(
                    'failed_command_output',
                    'failed-command:helper:1',
                    5,
                    1,
                    '3',
                ),
                component('reference', 'references/release.md', 8, 1, '4'),
                component('reference', 'references/release.md', 8, 2, '4'),
            ],
        }
        projected = load_analyzer_module()._v4_context_projection(context)
        self.assertEqual(18, projected['unique_static_content_bytes'])
        self.assertEqual(18, projected['repeated_static_content_bytes'])
        self.assertEqual(7, projected['protocol_output_bytes'])
        self.assertEqual(5, projected['failed_command_output_bytes'])
        self.assertEqual(10, projected['host_integration_duplicate_bytes'])
        self.assertEqual(
            8, projected['unexplained_repeated_static_content_bytes'],
        )
        invalid = copy.deepcopy(context)
        invalid['controlled_bytes'] += 1
        with self.assertRaisesRegex(ValueError, 'accounting failed'):
            load_analyzer_module()._v4_context_projection(invalid)
            self.assertIn('evidence_status=invalid', invalid.stdout)


    def test_prior_context_delta_is_variant_scoped_and_fail_closed(self) -> None:
        analyzer = load_analyzer_module()
        cases = {
            case_id: {
                'should_trigger': True,
                'attribution_evaluable': True,
                'applicable_variant_profiles': [
                    'candidate/natural_routing', 'prior/natural_routing',
                ],
            }
            for case_id in ('case-a', 'case-b')
        }
        candidate_only_spec = {'variants': [
            {'id': 'candidate', 'role': 'candidate', 'mode': 'natural_routing'},
        ]}

        def row(
            variant: str, case_id: str, size: int, *, source: str = 'replay_manifest',
            attributed: bool = True, valid: bool = True, task_pass: bool = True,
        ) -> dict:
            return {
                'variant': variant, 'case_id': case_id, 'repeat': 1,
                'valid': valid, 'task_pass': task_pass,
                'context_usage': {
                    'attributed': attributed, 'bytes': size, 'tokens': None,
                    'measurement_source': source, 'components': [],
                    'unique_static_content_bytes': size,
                    'repeated_static_content_bytes': 0,
                    'protocol_output_bytes': 0,
                    'failed_command_output_bytes': 0,
                    'host_integration_duplicate_bytes': 0,
                    'unexplained_repeated_static_content_bytes': 0,
                    'unattributed_model_body_read_count': 0,
                    'controlled_bytes': size,
                    'unique_reference_bytes': 0,
                    'controlled_core_bytes': size,
                },
            }

        candidate_rows = [row('candidate', 'case-a', 100), row('candidate', 'case-b', 200)]
        default_summary = analyzer.summarize_skill_context(candidate_rows, cases, candidate_only_spec, 1)
        explicit_summary = analyzer.summarize_skill_context(
            candidate_rows, cases, candidate_only_spec, 1,
            role='candidate', mode='natural_routing',
        )
        self.assertEqual(default_summary, explicit_summary)
        self.assertEqual(
            {'p50': 100, 'p95': 200, 'max': 200},
            default_summary['context_efficiency']['unique_static_content_bytes'],
        )
        self.assertEqual(200, default_summary['controlled_skill_context_bytes_p95'])
        self.assertEqual(0, default_summary['unattributed_model_body_read_count_max'])
        resolve = lambda metric: analyzer.resolve_gate_metric(  # noqa: E731
            metric, {}, {}, [], None, None, None, None, cases, 1,
            context_summary=default_summary,
        )
        self.assertEqual(200, resolve('controlled_skill_context_bytes_p95'))
        self.assertEqual(0, resolve('host_integration_duplicate_bytes_max'))
        self.assertEqual(0, resolve('unexplained_repeated_static_content_bytes_max'))
        self.assertEqual(0, resolve('unattributed_model_body_read_count_max'))
        for field in (
            'repeated_static_content_bytes', 'protocol_output_bytes',
            'failed_command_output_bytes', 'host_integration_duplicate_bytes',
            'unexplained_repeated_static_content_bytes',
        ):
            self.assertEqual({'p50': 0, 'p95': 0, 'max': 0}, default_summary['context_efficiency'][field])
        self.assertIsNone(analyzer.summarize_prior_skill_context(
            candidate_rows, cases, candidate_only_spec, 1, default_summary,
        ))

        spec = {'variants': [
            {'id': 'candidate', 'role': 'candidate', 'mode': 'natural_routing'},
            {'id': 'prior', 'role': 'prior', 'mode': 'natural_routing'},
        ]}
        prior_rows = [row('prior', 'case-a', 150), row('prior', 'case-b', 160)]
        comparison = analyzer.summarize_prior_skill_context(
            candidate_rows + prior_rows, cases, spec, 1, default_summary,
        )
        self.assertEqual(160, comparison['prior_skill_context']['bytes_p95'])
        self.assertEqual(40, comparison['candidate_minus_prior_bytes_p95'])

        forced_cases = {
            case_id: {
                **case,
                'applicable_variant_profiles': [
                    'candidate/force_loaded', 'prior/force_loaded',
                ],
            }
            for case_id, case in cases.items()
        }
        forced_spec = {'variants': [
            {'id': 'candidate', 'role': 'candidate', 'mode': 'force_loaded'},
            {'id': 'prior', 'role': 'prior', 'mode': 'force_loaded'},
        ]}
        forced_summary = analyzer.summarize_skill_context(
            candidate_rows, forced_cases, forced_spec, 1, mode='force_loaded',
        )
        forced_comparison = analyzer.summarize_prior_skill_context(
            candidate_rows + prior_rows, forced_cases, forced_spec, 1,
            forced_summary, mode='force_loaded',
        )
        self.assertEqual(160, forced_comparison['prior_skill_context']['bytes_p95'])
        self.assertEqual(40, forced_comparison['candidate_minus_prior_bytes_p95'])

        failed_candidate_rows = [
            row('candidate', 'case-a', 100, task_pass=False),
            candidate_rows[1],
        ]
        failed_summary = analyzer.summarize_skill_context(
            failed_candidate_rows + prior_rows, cases, spec, 1,
        )
        failed_comparison = analyzer.summarize_prior_skill_context(
            failed_candidate_rows + prior_rows, cases, spec, 1, failed_summary,
        )
        self.assertEqual(40, failed_comparison['candidate_minus_prior_bytes_p95'])
        paired_context = analyzer.summarize_paired_metric(
            failed_candidate_rows + prior_rows,
            comparator='prior', candidate='candidate',
            metric='controlled_core_skill_context_bytes',
            direction='lower_is_better', effect='relative',
            confidence_level=0.95, bootstrap_iterations=100, random_seed=1729,
        )
        self.assertEqual(2, paired_context['case_count'])
        self.assertEqual([], paired_context['task_failures'])

        unavailable_inputs = {
            'missing receipt': candidate_rows + prior_rows[:1],
            'duplicate receipt': candidate_rows + prior_rows + [prior_rows[0]],
            'invalid receipt': candidate_rows + [
                row('prior', 'case-a', 150, valid=False), prior_rows[1],
            ],
            'paired total only': candidate_rows + [
                row('prior', 'case-a', 150, source='paired_total_only', attributed=False), prior_rows[1],
            ],
            'measurement mismatch': candidate_rows + [
                row('prior', 'case-a', 150, source='host_receipt'),
                row('prior', 'case-b', 160, source='host_receipt'),
            ],
        }
        for label, rows in unavailable_inputs.items():
            with self.subTest(label=label):
                candidate_summary = analyzer.summarize_skill_context(rows, cases, spec, 1)
                unavailable = analyzer.summarize_prior_skill_context(
                    rows, cases, spec, 1, candidate_summary,
                )
                self.assertIsNone(unavailable['candidate_minus_prior_bytes_p95'])

        duplicate_prior_spec = {'variants': [
            *spec['variants'],
            {'id': 'prior-2', 'role': 'prior', 'mode': 'natural_routing'},
        ]}
        duplicate_prior = analyzer.summarize_prior_skill_context(
            candidate_rows + prior_rows, cases, duplicate_prior_spec, 1, default_summary,
        )
        self.assertIsNone(duplicate_prior['prior_skill_context'])
        self.assertIsNone(duplicate_prior['candidate_minus_prior_bytes_p95'])


    def test_context_summaries_exclude_non_attribution_cases_for_candidate_and_prior(self) -> None:
        analyzer = load_analyzer_module()
        cases = {
            'eligible': {
                'should_trigger': True,
                'attribution_evaluable': True,
                'applicable_variant_profiles': [
                    'candidate/natural_routing', 'prior/natural_routing',
                ],
            },
            'protected': {
                'should_trigger': True,
                'attribution_evaluable': False,
                'applicable_variant_profiles': [
                    'candidate/natural_routing', 'prior/natural_routing',
                ],
            },
        }
        spec = {'variants': [
            {'id': 'candidate', 'role': 'candidate', 'mode': 'natural_routing'},
            {'id': 'prior', 'role': 'prior', 'mode': 'natural_routing'},
        ]}

        def row(variant: str, case_id: str, size: int) -> dict:
            return {
                'variant': variant, 'case_id': case_id, 'repeat': 1,
                'valid': True, 'task_pass': True,
                'context_usage': {
                    'attributed': True, 'bytes': size, 'tokens': None,
                    'measurement_source': 'replay_manifest', 'components': [],
                    'unique_static_content_bytes': size,
                    'repeated_static_content_bytes': 0,
                    'protocol_output_bytes': 0,
                    'failed_command_output_bytes': 0,
                    'host_integration_duplicate_bytes': 0,
                    'unexplained_repeated_static_content_bytes': 0,
                    'unattributed_model_body_read_count': 0,
                    'controlled_bytes': size,
                    'unique_reference_bytes': 0,
                    'controlled_core_bytes': size,
                },
            }

        rows = [
            row('candidate', 'eligible', 100), row('candidate', 'protected', 10_000),
            row('prior', 'eligible', 150), row('prior', 'protected', 20_000),
        ]
        candidate = analyzer.summarize_skill_context(rows, cases, spec, 1)
        self.assertEqual(candidate['planned_rows'], 1)
        self.assertEqual(candidate['attributed_rows'], 1)
        self.assertEqual(candidate['bytes_p95'], 100)
        comparison = analyzer.summarize_prior_skill_context(rows, cases, spec, 1, candidate)
        self.assertEqual(comparison['prior_skill_context']['planned_rows'], 1)
        self.assertEqual(comparison['prior_skill_context']['bytes_p95'], 150)
        self.assertEqual(comparison['candidate_minus_prior_bytes_p95'], -50)


    def test_context_cost_without_declared_benefit_is_not_supported(self) -> None:
        analyzer = load_analyzer_module()
        self.assertEqual(
            analyzer.derive_usefulness_status(
                level='L2', evidence_status='complete', primary_benefit_status='fail',
                guardrail_statuses=['pass', 'pass'], protected_outcome_failures=0,
                material_harm=False, candidate_hard_failures=0,
            ),
            'not_supported',
        )


    def test_l1_smoke_expected_negative_is_diagnostic_rc_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._materialize_v5_analysis_bundle(root)
            self._rewrite_v5_outcomes(
                paths, {('candidate', 'case-basic')},
            )
            result = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
            )
            summary = json.loads(paths['summary'].read_text(encoding='utf-8'))
            failures = json.loads(paths['failures'].read_text(encoding='utf-8'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(summary['evidence_status'], 'complete')
        self.assertEqual(summary['usefulness_status'], 'not_evaluable')
        self.assertNotIn('run_matrix', summary)
        self.assertIn(
            'treatment.failed',
            {item['code'] for item in failures['failures']},
        )


    def test_v5_status_stream_does_not_replace_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_v5_analysis_bundle(Path(tmp))
            result = self.call_cli(
                'scripts/analyze_runs.py',
                str(paths['index']),
                '--spec', str(paths['spec']),
                '--json', str(paths['summary']),
                '--failure-index', str(paths['failures']),
                '--markdown', str(paths['markdown']),
            )
            report = json.loads(paths['summary'].read_text(encoding='utf-8'))
            markdown = paths['markdown'].read_text(encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(report['evidence_status'], 'complete')
        self.assertFalse(result.stdout.lstrip().startswith('{'))
        self.assertIn('Analyzed 2 attempts', result.stdout)
        self.assertIn('Evidence: `complete`', markdown)

    def test_l4_claims_stop_at_version_cycle_monitoring_without_orchestration_receipts(self) -> None:
        for name in (
            'evaluation-contract.md', 'longitudinal-evaluation.md', 'reporting-and-decisions.md',
        ):
            text = (ROOT / 'references' / name).read_text(encoding='utf-8')
            self.assertIn('L4 is limited to version and cycle monitoring', text, name)
            self.assertIn('selection, order, and composition receipts', text, name)
            self.assertIn('must not claim library-scale multi-Skill orchestration evidence', text, name)


    def test_summarize_case_differences_is_importable_and_deterministic(self) -> None:
        analyzer = load_analyzer_module()
        values = [-1.0, -0.5, 0.0, 0.25, 0.5, 1.0, 1.0, 1.0]
        kwargs = dict(confidence_level=0.95, bootstrap_iterations=500, random_seed=11)
        self.assertEqual(
            analyzer.summarize_case_differences(values, **kwargs),
            analyzer.summarize_case_differences(values, **kwargs),
        )


if __name__ == '__main__':
    unittest.main()  # noqa: F405
