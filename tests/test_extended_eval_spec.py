from __future__ import annotations

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedEvalSpec(SkillEvaluatorTestCase):  # noqa: F405
    def test_validator_cli_accepts_public_l0_smoke(self) -> None:
        result = self.run_cmd(
            'scripts/validate_eval_suite.py', 'templates/eval-spec.l0.example.json',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validator_cli_rejects_old_schema_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = make_minimal_spec('L0')
            spec['schema_version'] = 3
            path = Path(tmp) / 'old-spec.json'
            path.write_text(json.dumps(spec), encoding='utf-8')
            result = self.run_cmd('scripts/validate_eval_suite.py', str(path))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('schema_version must equal 4', result.stdout)

    def test_spec_contract_acceptance_is_shared(self) -> None:
        spec = json.loads((ROOT / 'templates/eval-spec.example.json').read_text(encoding='utf-8'))
        spec['environment']['random_seed'] = None
        spec['suite']['cases_file'] = str(ROOT / 'templates/cases.example.jsonl')
        for grader in spec['graders']:
            if grader.get('schema'):
                grader['schema'] = str(ROOT / 'templates/grader-output.schema.json')

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / 'spec.json'
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            validator = self.call_cli(
                'scripts/validate_eval_suite.py',
                str(spec_path), str(ROOT / 'templates/cases.example.jsonl'),
            )
            analyzer = self.call_cli(
                'scripts/analyze_runs.py', 'templates/runs.example.jsonl',
                '--spec', str(spec_path), '--report-only',
            )

        expected = 'spec.environment.random_seed must be an integer for L2+'
        self.assertEqual(validator.returncode, 1, validator.stdout + validator.stderr)
        self.assertEqual(analyzer.returncode, 2, analyzer.stdout + analyzer.stderr)
        self.assertIn(expected, validator.stdout + validator.stderr)
        self.assertIn(expected, analyzer.stdout + analyzer.stderr)


    def test_case_contract_acceptance_is_shared(self) -> None:
        cases = [
            json.loads(line)
            for line in (ROOT / 'templates/cases.example.jsonl').read_text(encoding='utf-8').splitlines()
        ]
        cases[0]['attribution_evaluable'] = False
        cases[0]['applicable_variant_profiles'] = []
        spec = json.loads((ROOT / 'templates/eval-spec.example.json').read_text(encoding='utf-8'))
        for grader in spec['graders']:
            if grader.get('schema'):
                grader['schema'] = str(ROOT / 'templates/grader-output.schema.json')

        with tempfile.TemporaryDirectory() as tmp:
            cases_path = Path(tmp) / 'cases.jsonl'
            spec_path = Path(tmp) / 'spec.json'
            cases_path.write_text(
                '\n'.join(json.dumps(case, separators=(',', ':')) for case in cases) + '\n',
                encoding='utf-8',
            )
            spec['suite']['cases_file'] = str(cases_path)
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            validator = self.call_cli(
                'scripts/validate_eval_suite.py', str(spec_path), str(cases_path),
            )
            analyzer = self.call_cli(
                'scripts/analyze_runs.py', 'templates/runs.example.jsonl',
                '--spec', str(spec_path), '--report-only',
            )

        expected = 'applicable_variant_profiles must be a non-empty string array'
        self.assertEqual(validator.returncode, 1, validator.stdout + validator.stderr)
        self.assertEqual(analyzer.returncode, 2, analyzer.stdout + analyzer.stderr)
        self.assertIn(expected, validator.stdout + validator.stderr)
        self.assertIn(expected, analyzer.stdout + analyzer.stderr)


    def test_minimal_level_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            l0_path = root / 'l0.json'
            l0_path.write_text(json.dumps(make_minimal_spec('L0')), encoding='utf-8')
            l0 = self.call_cli('scripts/validate_eval_suite.py', str(l0_path))

            cases_path = root / 'cases.jsonl'
            cases_path.write_text(
                '\n'.join(json.dumps(case) for case in make_minimal_cases()) + '\n',
                encoding='utf-8',
            )
            l1_spec = make_minimal_spec('L1')
            l1_path = root / 'l1.json'
            l1_path.write_text(json.dumps(l1_spec), encoding='utf-8')
            l1 = self.call_cli('scripts/validate_eval_suite.py', str(l1_path), str(cases_path))

            comparative_cases = make_minimal_cases(comparative=True)
            cases_path.write_text(
                '\n'.join(json.dumps(case) for case in comparative_cases) + '\n',
                encoding='utf-8',
            )
            l2_spec = make_minimal_spec('L2')
            l2_path = root / 'l2.json'
            l2_path.write_text(json.dumps(l2_spec), encoding='utf-8')
            l2 = self.call_cli('scripts/validate_eval_suite.py', str(l2_path), str(cases_path))

            overclaimed_l1 = make_minimal_spec('L1')
            overclaimed_l1['analysis'] = {'confidence_level': 0.95, 'paired_bootstrap_iterations': 100}
            overclaimed_l1_path = root / 'l1-overclaimed.json'
            overclaimed_l1_path.write_text(json.dumps(overclaimed_l1), encoding='utf-8')
            overclaimed = self.call_cli(
                'scripts/validate_eval_suite.py', str(overclaimed_l1_path), str(cases_path),
            )

            l3_spec = make_minimal_spec('L2')
            l3_spec['level'] = 'L3'
            l3_path = root / 'l3-missing-controls.json'
            l3_path.write_text(json.dumps(l3_spec), encoding='utf-8')
            l3_missing = self.call_cli(
                'scripts/validate_eval_suite.py', str(l3_path), str(cases_path),
            )

            old_version = make_minimal_spec('L0')
            old_version['schema_version'] = 1
            old_path = root / 'v1.json'
            old_path.write_text(json.dumps(old_version), encoding='utf-8')
            v1 = self.call_cli('scripts/validate_eval_suite.py', str(old_path))

        self.assertEqual(l0.returncode, 0, l0.stdout + l0.stderr)
        self.assertIn('VALID: 0 cases', l0.stdout)
        self.assertEqual(l1.returncode, 0, l1.stdout + l1.stderr)
        self.assertEqual(l2.returncode, 0, l2.stdout + l2.stderr)
        self.assertEqual(overclaimed.returncode, 1, overclaimed.stdout + overclaimed.stderr)
        self.assertIn('L1 spec forbids analysis', overclaimed.stdout)
        self.assertEqual(l3_missing.returncode, 1, l3_missing.stdout + l3_missing.stderr)
        self.assertIn('L3/L4 spec requires suite.holdout_control', l3_missing.stdout)
        self.assertIn('L3/L4 spec requires manual_review.required=true', l3_missing.stdout)
        self.assertEqual(v1.returncode, 1, v1.stdout + v1.stderr)
        self.assertIn('spec.schema_version must equal 4', v1.stdout)


    def test_schema_v4_rejects_legacy_spec_and_case_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L1')
            rows = make_minimal_cases()
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            valid = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            self.assertIn('non-ready deterministic verifier placeholder', valid.stdout)
            self.assertIn('non-ready fixture manifest placeholder', valid.stdout)

            legacy_spec = json.loads(json.dumps(spec))
            legacy_spec['schema_version'] = 2
            spec_path, cases_path = write_spec_bundle(root, legacy_spec, rows)
            old_spec = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(old_spec.returncode, 1, old_spec.stdout + old_spec.stderr)
            self.assertIn('spec.schema_version must equal 4', old_spec.stdout)

            legacy_rows = json.loads(json.dumps(rows))
            legacy_rows[0]['oracle'] = ['focused-check']
            spec_path, cases_path = write_spec_bundle(root, spec, legacy_rows)
            old_case = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(old_case.returncode, 1, old_case.stdout + old_case.stderr)
            self.assertIn('forbidden legacy field oracle', old_case.stdout)


    def test_schema_v4_rejects_unmapped_duplicate_or_optional_safety_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L1')
            spec['graders'].append({
                'id': 'safety-check',
                'type': 'deterministic',
                'hard_gate': True,
                'version': '2',
                'checks': [{'id': 'no-write', 'pass_condition': 'No unauthorized write occurs.'}],
                'verifier': {
                    'path': 'graders/safety-check.py',
                    'sha256': 'sha256:replace-before-scored-run',
                    'argv': ['python3', 'graders/safety-check.py'],
                    'pass_exit_codes': [0],
                },
            })
            rows = make_minimal_cases()
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            valid = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

            unmapped = json.loads(json.dumps(rows))
            unmapped[0]['requirements'][0]['check_id'] = 'unknown-check'
            spec_path, cases_path = write_spec_bundle(root, spec, unmapped)
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('references unknown check', result.stdout)

            duplicate = json.loads(json.dumps(rows))
            copied = dict(duplicate[0]['requirements'][0])
            copied['id'] = 'duplicate-binding'
            duplicate[0]['requirements'].append(copied)
            spec_path, cases_path = write_spec_bundle(root, spec, duplicate)
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('duplicate grader/check binding', result.stdout)

            optional_safety = json.loads(json.dumps(rows))
            optional_safety[0]['requirements'].append({
                'id': 'no-unauthorized-write',
                'dimension': 'safety',
                'required': False,
                'severity': 'critical',
                'safety_kind': 'unauthorized_action',
                'grader_id': 'safety-check',
                'check_id': 'no-write',
            })
            spec_path, cases_path = write_spec_bundle(root, spec, optional_safety)
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('safety requirement must be required', result.stdout)


    def test_schema_v4_derives_exact_grader_set_from_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L1')
            spec['graders'].append({
                'id': 'unused-check',
                'type': 'deterministic',
                'hard_gate': False,
                'version': '2',
                'checks': [{'id': 'unused', 'pass_condition': 'An unused check.'}],
            })
            rows = make_minimal_cases()
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            unselected = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(unselected.returncode, 0, unselected.stdout + unselected.stderr)

            selected_rows = json.loads(json.dumps(rows))
            selected_rows[0]['requirements'][0].update({
                'grader_id': 'unused-check',
                'check_id': 'unused',
            })
            spec_path, cases_path = write_spec_bundle(root, spec, selected_rows)
            selected = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(selected.returncode, 1, selected.stdout + selected.stderr)
            self.assertIn('selected deterministic grader unused-check must declare verifier', selected.stdout)


    def test_schema_v4_rejects_unknown_or_duplicate_declared_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L2')
            rows = make_minimal_cases(comparative=True)
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            valid = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

            unknown = json.loads(json.dumps(spec))
            unknown['metrics'] = ['unknown_metric']
            spec_path, cases_path = write_spec_bundle(root, unknown, rows)
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('unsupported declared metric', result.stdout)

            duplicate = json.loads(json.dumps(spec))
            duplicate['metrics'] = ['task_pass_rate', 'task_pass_rate']
            spec_path, cases_path = write_spec_bundle(root, duplicate, rows)
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('spec.metrics must not contain duplicates', result.stdout)


    def test_schema_v4_rejects_legacy_deterministic_grader_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L1')
            rows = make_minimal_cases()
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            valid = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

            for grader_type in ('deterministic_trace', 'deterministic_security', 'deterministic_custom'):
                invalid = json.loads(json.dumps(spec))
                invalid['graders'][0]['type'] = grader_type
                spec_path, cases_path = write_spec_bundle(root, invalid, rows)
                result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('grader type must be one of', result.stdout)


    def test_schema_v4_rejects_ready_deterministic_verifier_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path, cases_path = write_spec_bundle(
                root, make_minimal_spec('L1'), make_minimal_cases(), ready=True,
            )
            valid = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

            spec = json.loads(spec_path.read_text(encoding='utf-8'))
            spec['graders'][0]['verifier']['sha256'] = 'sha256:replace-before-scored-run'
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('scored-ready deterministic verifier placeholder is forbidden', result.stdout)


    def test_schema_v4_rejects_selected_nonhard_deterministic_without_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L1')
            rows = make_minimal_cases()
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            valid = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

            invalid = json.loads(json.dumps(spec))
            self.assertFalse(invalid['graders'][0]['hard_gate'])
            invalid['graders'][0].pop('verifier')
            spec_path, cases_path = write_spec_bundle(root, invalid, rows)
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('selected deterministic grader focused-check must declare verifier', result.stdout)


    def test_schema_v4_rejects_ready_fixture_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path, cases_path = write_spec_bundle(
                root, make_minimal_spec('L1'), make_minimal_cases(), ready=True,
            )
            valid = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

            rows = [json.loads(line) for line in cases_path.read_text(encoding='utf-8').splitlines()]
            rows[0]['fixture'] = {
                'manifest': 'fixtures/replace-before-scored-run.manifest.json',
                'sha256': 'sha256:replace-before-scored-run',
            }
            cases_path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n', encoding='utf-8')
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(cases_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('scored-ready fixture manifest placeholder is forbidden', result.stdout)


    def test_cost_primary_requires_task_quality_safety_and_authority_protection(self) -> None:
        analyzer = load_analyzer_module()
        spec = make_minimal_spec('L2')
        spec['analysis']['primary_benefit'] = {
            'metric': 'tokens_in', 'comparator': 'baseline',
            'direction': 'lower_is_better', 'effect': 'relative', 'minimum_benefit': 0.1,
        }
        spec['metrics'] = [
            'tokens_in', 'task_pass_rate', 'quality_score_normalized', 'safety_pass_rate',
        ]
        spec['hard_gates'] = [
            {'id': 'task-ni', 'metric': 'task_pass_rate', 'comparator': 'baseline',
             'direction': 'higher_is_better', 'effect': 'absolute', 'minimum_benefit': -0.05},
            {'id': 'quality-ni', 'metric': 'quality_score_normalized', 'comparator': 'baseline',
             'direction': 'higher_is_better', 'effect': 'absolute', 'minimum_benefit': -0.05},
            {'id': 'safety-ni', 'metric': 'safety_pass_rate', 'comparator': 'baseline',
             'direction': 'higher_is_better', 'effect': 'absolute', 'minimum_benefit': 0.0},
            {'id': 'authority', 'metric': 'unauthorized_side_effects', 'operator': '==', 'value': 0},
            {'id': 'protected', 'metric': 'protected_outcome_failures', 'operator': '==', 'value': 0},
        ]
        errors: list[str] = []
        analyzer.check_spec(spec, errors, [])
        self.assertEqual([], errors)

        for gate_id, expected in (
            ('task-ni', 'task/quality/safety'),
            ('quality-ni', 'task/quality/safety'),
            ('safety-ni', 'task/quality/safety'),
            ('authority', 'authority protection'),
        ):
            with self.subTest(gate_id=gate_id):
                mutated = copy.deepcopy(spec)
                mutated['hard_gates'] = [gate for gate in mutated['hard_gates'] if gate['id'] != gate_id]
                errors = []
                analyzer.check_spec(mutated, errors, [])
                self.assertTrue(any(expected in error for error in errors), errors)


    def test_non_task_primary_benefit_requires_task_noninferiority(self) -> None:
        analyzer = load_analyzer_module()
        spec = make_minimal_spec('L2')
        spec['analysis']['primary_benefit'] = {
            'metric': 'process_score_normalized', 'comparator': 'baseline',
            'direction': 'higher_is_better', 'effect': 'absolute', 'minimum_benefit': 0.02,
        }
        spec['metrics'] = ['process_score_normalized']
        errors: list[str] = []
        analyzer.check_spec(spec, errors, [])
        self.assertTrue(any('task_pass_rate noninferiority' in error for error in errors), errors)


    def test_context_budget_requires_external_authority_and_exact_gate_id(self) -> None:
        analyzer = load_analyzer_module()
        spec = make_minimal_spec('L2')
        spec['ready_for_scored_run'] = True
        spec['analysis'].update({
            'context_budget_gate_id': 'skill-context-budget',
            'context_budget_authority': {
                'kind': 'deployment_contract', 'reference': 'sha256:' + 'a' * 64,
                'unit': 'bytes', 'threshold': 4096,
            },
        })
        spec['hard_gates'].extend([
            {'id': 'context-attribution', 'metric': 'skill_context_attribution_rate', 'operator': '==', 'value': 1},
            {'id': 'skill-context-budget', 'metric': 'skill_context_bytes_p95', 'operator': '<=', 'value': 4096},
            {'id': 'controlled-context-budget', 'metric': 'controlled_skill_context_bytes_p95', 'operator': '<=', 'value': 4096},
            {'id': 'host-duplicate-budget', 'metric': 'host_integration_duplicate_bytes_max', 'operator': '<=', 'value': 4096},
            {'id': 'protected', 'metric': 'protected_outcome_failures', 'operator': '==', 'value': 0},
            {'id': 'unexplained-repeated', 'metric': 'unexplained_repeated_static_content_bytes_max', 'operator': '==', 'value': 0},
            {'id': 'unattributed-reread', 'metric': 'unattributed_model_body_read_count_max', 'operator': '==', 'value': 0},
            {'id': 'protocol-output', 'metric': 'protocol_output_bytes_max', 'operator': '==', 'value': 0},
            {'id': 'failed-output', 'metric': 'failed_command_output_bytes_max', 'operator': '==', 'value': 0},
        ])
        errors: list[str] = []
        analyzer.check_spec(spec, errors, [])
        self.assertFalse([
            error for error in errors
            if 'context budget' in error or 'context_budget' in error or 'bytes_max == 0 gate' in error
        ], errors)

        spec['hard_gates'][-1]['value'] = 1
        errors = []
        analyzer.check_spec(spec, errors, [])
        self.assertIn(
            'scored-ready L2+ spec requires one failed_command_output_bytes_max == 0 gate',
            errors,
        )
        spec['hard_gates'][-1]['value'] = 0

        spec['analysis']['context_budget_authority']['reference'] = 'sha256:ABC'
        spec['analysis']['context_budget_gate_id'] = 'wrong-id'
        errors = []
        analyzer.check_spec(spec, errors, [])
        self.assertTrue(any('context_budget' in error or 'context budget' in error for error in errors), errors)


    def test_nonready_context_budget_placeholder_warns_and_ready_rejects(self) -> None:
        analyzer = load_analyzer_module()
        spec = make_minimal_spec('L2')
        errors: list[str] = []
        warnings: list[str] = []
        analyzer.check_spec(spec, errors, warnings)
        self.assertNotIn('non-ready context budget placeholder', errors)
        self.assertIn('non-ready context budget placeholder', warnings)

        spec['ready_for_scored_run'] = True
        errors = []
        analyzer.check_spec(spec, errors, [])
        self.assertTrue(any('context budget' in error or 'context_budget' in error for error in errors), errors)


    def test_level_specific_contract_rejections_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def validate(name: str, spec: dict, cases: list[dict] | None = None):
                spec = json.loads(json.dumps(spec))
                cases_path = None
                if cases is not None:
                    cases_path = root / f'{name}.jsonl'
                    spec['suite']['cases_file'] = cases_path.name
                spec_path = root / f'{name}.json'
                spec_path.write_text(json.dumps(spec), encoding='utf-8')
                args = ['scripts/validate_eval_suite.py', str(spec_path)]
                if cases is not None:
                    cases_path.write_text(
                        '\n'.join(json.dumps(case) for case in cases) + '\n',
                        encoding='utf-8',
                    )
                    args.append(str(cases_path))
                return self.call_cli(*args)

            l0_overclaim = make_minimal_spec('L0')
            l0_overclaim['suite'] = {'cases_file': 'cases.jsonl'}
            l0_result = validate('l0-overclaim', l0_overclaim)
            l0_path = root / 'l0-analyzer.json'
            l0_path.write_text(json.dumps(make_minimal_spec('L0')), encoding='utf-8')
            l0_analyzer = self.call_cli(
                'scripts/analyze_runs.py', str(root / 'missing-runs.jsonl'),
                '--spec', str(l0_path), '--report-only',
            )

            l1_overclaim = make_minimal_spec('L1')
            l1_overclaim.update({
                'analysis': {},
                'metrics': [],
                'hard_gates': [],
                'ready_for_scored_run': False,
            })
            payload = ROOT / 'templates/holdout-cases.example.jsonl'
            manifest = ROOT / 'templates/holdout-manifest.example.json'
            l1_overclaim['suite']['holdout_control'] = {
                **READY_HOLDOUT_CONTROL,
                'payload_file': str(payload),
                'manifest_file': str(manifest),
                'payload_hash': 'sha256:' + hashlib.sha256(payload.read_bytes()).hexdigest(),
                'manifest_hash': 'sha256:' + hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }
            l1_result = validate('l1-overclaim', l1_overclaim, make_minimal_cases())

            l2_missing_pair = make_minimal_spec('L2')
            l2_missing_pair['variants'] = [
                variant for variant in l2_missing_pair['variants'] if variant['role'] != 'baseline'
            ]
            l2_result = validate(
                'l2-missing-pair', l2_missing_pair, make_minimal_cases(comparative=True),
            )
            l2_missing_candidate = make_minimal_spec('L2')
            l2_missing_candidate['variants'] = [
                variant for variant in l2_missing_candidate['variants']
                if variant['role'] != 'candidate'
            ]
            l2_missing_candidate_result = validate(
                'l2-missing-candidate', l2_missing_candidate,
                make_minimal_cases(comparative=True),
            )

            explicit_l2 = make_minimal_spec('L2')
            explicit_l2['variants'][1].update({
                'id': 'candidate_explicit', 'mode': 'force_loaded',
            })
            explicit_l2['hard_gates'][0]['metric'] = 'candidate_explicit.task_pass_rate'
            explicit_l2['target']['prior_hash'] = 'sha256:' + '9' * 64
            explicit_l2['variants'].append({
                'id': 'prior_explicit',
                'role': 'prior',
                'mode': 'force_loaded',
                'package_hash': explicit_l2['target']['prior_hash'],
                'catalog_hash': 'sha256:' + 'a' * 64,
                'treatment_hash': 'sha256:' + 'b' * 64,
            })
            explicit_cases = make_minimal_cases(comparative=True)
            for case in explicit_cases:
                case['applicable_variant_profiles'] = [
                    'baseline/skill_disabled',
                    'candidate/force_loaded',
                    'prior/force_loaded',
                ]
            explicit_result = validate('l2-explicit', explicit_l2, explicit_cases)

            mixed_l2 = json.loads(json.dumps(explicit_l2))
            mixed_l2['variants'].append({
                'id': 'candidate_natural',
                'role': 'candidate',
                'mode': 'natural_routing',
                'package_hash': mixed_l2['target']['candidate_hash'],
                'catalog_hash': 'sha256:' + 'c' * 64,
                'treatment_hash': 'sha256:' + 'd' * 64,
            })
            mixed_cases = json.loads(json.dumps(explicit_cases))
            for case in mixed_cases:
                case['applicable_variant_profiles'].append('candidate/natural_routing')
            mixed_result = validate('l2-mixed-candidates', mixed_l2, mixed_cases)

            high_risk = make_minimal_spec('L2')
            high_risk['risk_tier'] = 'high'
            high_risk_result = validate(
                'high-risk', high_risk, make_minimal_cases(comparative=True),
            )

            injection_cases = make_minimal_cases()
            injection_cases[0]['tags'].append('prompt-injection')
            injection_result = validate('missing-adversarial', make_minimal_spec('L1'), injection_cases)

        self.assertEqual(l0_result.returncode, 1)
        self.assertIn('L0 spec forbids suite', l0_result.stdout)
        self.assertEqual(l0_analyzer.returncode, 2)
        self.assertIn('L0 specs are package audits', l0_analyzer.stderr)
        self.assertEqual(l1_result.returncode, 1, l1_result.stdout + l1_result.stderr)
        for field in ('analysis', 'metrics', 'hard_gates'):
            self.assertIn(f'L1 spec forbids {field}', l1_result.stdout)
        self.assertIn('L1 spec forbids suite.holdout_control', l1_result.stdout)
        self.assertEqual(l2_result.returncode, 1)
        self.assertIn('L2+ spec must include a baseline/skill_disabled variant', l2_result.stdout)
        self.assertEqual(l2_missing_candidate_result.returncode, 1)
        self.assertIn(
            'L2+ spec must include a candidate/force_loaded or candidate/natural_routing variant',
            l2_missing_candidate_result.stdout,
        )
        self.assertEqual(explicit_result.returncode, 0, explicit_result.stdout + explicit_result.stderr)
        self.assertEqual(mixed_result.returncode, 0, mixed_result.stdout + mixed_result.stderr)
        self.assertEqual(high_risk_result.returncode, 1)
        self.assertIn('high-risk spec requires manual_review.required=true', high_risk_result.stdout)
        self.assertIn('high-risk or L3/L4 suite must include safety-tagged cases', high_risk_result.stdout)
        self.assertEqual(injection_result.returncode, 1)
        self.assertIn('prompt-injection case must declare adversarial_inputs', injection_result.stdout)


    def test_fail_closed_grader_example_matches_machine_schema(self) -> None:
        schema = json.loads((ROOT / 'templates/grader-output.schema.json').read_text(encoding='utf-8'))
        prompt = (ROOT / 'templates/llm-grader-prompt.md').read_text(encoding='utf-8')
        payload = prompt.split('```json\n', 1)[1].split('\n```', 1)[0]
        example = json.loads(payload)
        jsonschema.validate(instance=example, schema=schema)
        self.assertFalse(example['overall_pass'])
        evidence = [{
            'artifact': 'artifacts/trace.jsonl',
            'locator': {'start_line': 1, 'end_line': 1},
            'observation': 'The required state transition completed.',
        }]
        normal_pass = {
            'overall_pass': True,
            'score': 100,
            'checks': [{
                'id': 'required-check', 'pass': True, 'evidence': evidence,
                'notes': 'Observed directly.', 'uncertainty': 'none',
            }],
            'missing_evidence': [],
            'grader_failure': False,
            'grader_failure_reason': None,
        }
        normal_fail = json.loads(json.dumps(normal_pass))
        normal_fail.update({'overall_pass': False, 'score': 0})
        normal_fail['checks'][0].update({
            'pass': False, 'notes': 'The required state was absent.', 'uncertainty': 'low',
        })
        jsonschema.validate(instance=normal_pass, schema=schema)
        jsonschema.validate(instance=normal_fail, schema=schema)
        for reason in (
            'evidence bundle is unreadable',
            'grader timed out before producing checks',
            'evidence bundle is corrupt',
        ):
            failure = {
                'overall_pass': False,
                'score': 0,
                'checks': [],
                'missing_evidence': [{'check_id': None, 'item': reason}],
                'grader_failure': True,
                'grader_failure_reason': reason,
            }
            jsonschema.validate(instance=failure, schema=schema)

        invalid_normal = {**normal_fail, 'checks': []}
        invalid_failure = {
            'overall_pass': False,
            'score': 0,
            'checks': [],
            'missing_evidence': [],
            'grader_failure': True,
            'grader_failure_reason': 'grader crashed',
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_normal, schema=schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=invalid_failure, schema=schema)
        contradictory = {
            'overall_pass': True,
            'score': 100,
            'checks': [{
                'id': 'required-check', 'pass': False, 'evidence': evidence,
                'notes': 'Observed failure.', 'uncertainty': 'none',
            }],
            'missing_evidence': [],
            'grader_failure': False,
            'grader_failure_reason': None,
        }
        jsonschema.validate(instance=contradictory, schema=schema)
        spec = json.loads((ROOT / 'templates/eval-spec.example.json').read_text(encoding='utf-8'))
        rubric = next(grader for grader in spec['graders'] if grader['type'] == 'model_rubric')
        self.assertEqual(rubric['schema_path'], 'grader-output.schema.json')


    def test_scored_ready_spec_rejects_exposed_holdout(self) -> None:
        spec = json.loads((ROOT / 'templates/eval-spec.example.json').read_text(encoding='utf-8'))
        spec['ready_for_scored_run'] = True
        spec['suite']['cases_file'] = str(ROOT / 'templates/cases.example.jsonl')
        file_hash = lambda path: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path = ROOT / 'templates/holdout-manifest.example.json'
        payload_path = ROOT / 'templates/holdout-cases.example.jsonl'
        spec['suite']['holdout_control'] = {
            'payload_separated': False,
            'manifest_file': str(manifest_path),
            'payload_file': str(payload_path),
            'manifest_hash': file_hash(manifest_path),
            'payload_hash': file_hash(payload_path),
            'custodian': 'template-author',
            'exposure_status': 'exposed',
            'last_exposure_at': None,
            'refresh_required': True,
        }
        for grader in spec['graders']:
            if grader.get('schema'):
                grader['schema'] = str(ROOT / 'templates/grader-output.schema.json')
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / 'spec.json'
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            result = self.call_cli(
                'scripts/validate_eval_suite.py',
                str(spec_path),
                str(ROOT / 'templates/cases.example.jsonl'),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('scored-ready suite must keep holdout payload separate from the author-visible case file', result.stdout)
        self.assertIn('scored-ready holdout exposure_status must be sealed or refreshed', result.stdout)
        self.assertIn('scored-ready holdout_control.refresh_required must be false', result.stdout)


    def test_duplicate_case_is_rejected(self) -> None:
        first = (ROOT / 'templates/cases.example.jsonl').read_text(encoding='utf-8').splitlines()[0]
        with tempfile.TemporaryDirectory() as tmp:
            cases = Path(tmp) / 'cases.jsonl'
            cases.write_text(first + '\n' + first + '\n', encoding='utf-8')
            result = self.call_cli(
                'scripts/validate_eval_suite.py',
                'templates/eval-spec.example.json',
                str(cases),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('duplicate case IDs', result.stdout)


    def test_malformed_spec_shape_reports_errors_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / 'spec.json'
            spec.write_text(json.dumps({'schema_version': 1, 'graders': None, 'variants': None}), encoding='utf-8')
            result = self.call_cli(
                'scripts/validate_eval_suite.py', str(spec),
                'templates/cases.example.jsonl',
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('INVALID:', result.stdout)
        self.assertNotIn('Traceback', result.stdout + result.stderr)


    def test_boolean_fields_reject_numeric_zero_or_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            receipt['run']['valid'] = 1
            rewrite_bound_receipt(bundle, receipt)
            result = self.run_receipt_analysis(bundle)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn('run.valid must be boolean', result.stdout)


    def test_required_variant_profile_cannot_be_silently_omitted(self) -> None:
        spec = json.loads((ROOT / 'templates/eval-spec.example.json').read_text(encoding='utf-8'))
        spec['variant_profile_requirements'] = [
            {'profile': 'candidate/force_loaded', 'status': 'required'},
        ]
        spec['suite']['cases_file'] = str(ROOT / 'templates/cases.example.jsonl')
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = Path(tmp) / 'spec.json'
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            result = self.call_cli('scripts/analyze_runs.py', 'templates/runs.example.jsonl', '--spec', str(spec_path), '--report-only')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("required variant profiles are undeclared: ['candidate/force_loaded']", result.stderr)


    def test_public_holdout_and_manifest_boundaries_are_enforced(self) -> None:
        spec = json.loads((ROOT / 'templates/eval-spec.example.json').read_text(encoding='utf-8'))
        public_rows = [json.loads(line) for line in (ROOT / 'templates/cases.example.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        holdout_rows = [json.loads(line) for line in (ROOT / 'templates/holdout-cases.example.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            public_path = tmp_path / 'cases.jsonl'
            public_path.write_text('\n'.join(json.dumps(row, separators=(',', ':')) for row in public_rows + [holdout_rows[0]]) + '\n', encoding='utf-8')
            spec['suite']['cases_file'] = str(public_path)
            file_hash = lambda path: 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()
            control = spec['suite']['holdout_control'] = {
                **READY_HOLDOUT_CONTROL,
                'payload_file': str(ROOT / 'templates/holdout-cases.example.jsonl'),
                'manifest_file': str(ROOT / 'templates/holdout-manifest.example.json'),
                'payload_hash': file_hash(ROOT / 'templates/holdout-cases.example.jsonl'),
                'manifest_hash': file_hash(ROOT / 'templates/holdout-manifest.example.json'),
            }
            control['payload_file'] = str(ROOT / 'templates/holdout-cases.example.jsonl')
            control['manifest_file'] = str(ROOT / 'templates/holdout-manifest.example.json')
            spec_path = tmp_path / 'spec.json'
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            result = self.call_cli('scripts/validate_eval_suite.py', str(spec_path), str(public_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('public cases file contains heldout payload rows', result.stdout)

            clean_spec = json.loads((ROOT / 'templates/eval-spec.example.json').read_text(encoding='utf-8'))
            clean_public = tmp_path / 'clean-cases.jsonl'
            clean_payload = tmp_path / 'holdout-cases.jsonl'
            clean_manifest = tmp_path / 'holdout-manifest.json'
            clean_public.write_text((ROOT / 'templates/cases.example.jsonl').read_text(encoding='utf-8'), encoding='utf-8')
            clean_payload.write_text((ROOT / 'templates/holdout-cases.example.jsonl').read_text(encoding='utf-8'), encoding='utf-8')
            manifest = json.loads((ROOT / 'templates/holdout-manifest.example.json').read_text(encoding='utf-8'))
            manifest['cases'][0]['case_sha256'] = 'sha256:' + '0' * 64
            clean_manifest.write_text(json.dumps(manifest), encoding='utf-8')
            clean_spec['suite']['cases_file'] = clean_public.name
            clean_spec['suite']['holdout_control'] = {
                **READY_HOLDOUT_CONTROL,
                'payload_file': clean_payload.name,
                'manifest_file': clean_manifest.name,
                'payload_hash': file_hash(clean_payload),
                'manifest_hash': file_hash(clean_manifest),
            }
            clean_spec_path = tmp_path / 'clean-spec.json'
            clean_spec_path.write_text(json.dumps(clean_spec), encoding='utf-8')
            case_hash_result = self.call_cli('scripts/validate_eval_suite.py', str(clean_spec_path), str(clean_public))

            payload_manifest = json.loads((ROOT / 'templates/holdout-manifest.example.json').read_text(encoding='utf-8'))
            payload_manifest['payload_sha256'] = 'sha256:' + '0' * 64
            clean_manifest.write_text(json.dumps(payload_manifest), encoding='utf-8')
            clean_spec['suite']['holdout_control']['manifest_hash'] = file_hash(clean_manifest)
            clean_spec_path.write_text(json.dumps(clean_spec), encoding='utf-8')
            payload_hash_result = self.call_cli('scripts/validate_eval_suite.py', str(clean_spec_path), str(clean_public))
        self.assertEqual(case_hash_result.returncode, 1, case_hash_result.stdout + case_hash_result.stderr)
        self.assertIn('holdout manifest case_sha256 mismatch', case_hash_result.stdout)
        self.assertEqual(payload_hash_result.returncode, 1, payload_hash_result.stdout + payload_hash_result.stderr)
        self.assertIn('holdout manifest payload_sha256 does not match holdout payload bytes', payload_hash_result.stdout)


    def test_requirement_owner_must_match_exactly_one_grader_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L1')
            rows = make_minimal_cases()
            rows[0]['requirements'][0]['owner'] = 'model'
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            mismatch = self.call_cli(
                'scripts/validate_eval_suite.py', str(spec_path), str(cases_path),
            )

            rows[0]['requirements'][0]['owner'] = 'deterministic'
            rows[0]['requirements'].append(dict(rows[0]['requirements'][0]))
            rows[0]['requirements'][1]['id'] = 'task-complete-duplicate-owner'
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            duplicate = self.call_cli(
                'scripts/validate_eval_suite.py', str(spec_path), str(cases_path),
            )

        self.assertEqual(mismatch.returncode, 1, mismatch.stdout + mismatch.stderr)
        self.assertIn('owner model does not match grader type deterministic', mismatch.stdout)
        self.assertEqual(duplicate.returncode, 1, duplicate.stdout + duplicate.stderr)
        self.assertIn('duplicate grader/check binding', duplicate.stdout)


    def test_model_grader_output_is_bound_to_one_jsonl_batch_item(self) -> None:
        analyzer = load_analyzer_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = {
                'overall_pass': True, 'score': 100, 'checks': [],
                'missing_evidence': [], 'grader_failure': False,
                'grader_failure_reason': None,
            }
            line = json.dumps({
                'schema_version': 1,
                'batch_id': 'batch-001',
                'items': [
                    {'item_id': 'run-a:rubric', 'grader_id': 'rubric', 'output': output},
                    {'item_id': 'run-b:rubric', 'grader_id': 'rubric', 'output': output},
                ],
            }, sort_keys=True, separators=(',', ':'))
            path = root / 'grader-batches.jsonl'
            path.write_text(line + '\n', encoding='utf-8')
            reference = {
                'artifact': 'grader-batches.jsonl',
                'line': 1,
                'line_sha256': 'sha256:' + hashlib.sha256(line.encode()).hexdigest(),
                'batch_id': 'batch-001',
                'item_id': 'run-b:rubric',
            }
            loaded = analyzer.load_batched_grader_output(
                reference, root, expected_grader_id='rubric',
            )
            self.assertEqual(loaded, output)
            reference['line_sha256'] = 'sha256:' + '0' * 64
            with self.assertRaisesRegex(ValueError, 'batch line sha256 mismatch'):
                analyzer.load_batched_grader_output(
                    reference, root, expected_grader_id='rubric',
                )


    def test_requirement_owner_can_be_scoped_to_declared_variant_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = make_minimal_spec('L1')
            rows = make_minimal_cases()
            profile = rows[0]['applicable_variant_profiles'][0]
            rows[0]['requirements'][0]['applicable_variant_profiles'] = [profile]
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            valid = self.call_cli(
                'scripts/validate_eval_suite.py', str(spec_path), str(cases_path),
            )
            rows[0]['requirements'][0]['applicable_variant_profiles'] = ['prior/force_loaded']
            spec_path, cases_path = write_spec_bundle(root, spec, rows)
            invalid = self.call_cli(
                'scripts/validate_eval_suite.py', str(spec_path), str(cases_path),
            )

        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertEqual(invalid.returncode, 1, invalid.stdout + invalid.stderr)
        self.assertIn('requirement profiles are outside the case profiles', invalid.stdout)


    def test_v2_identity_bindings_are_required_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec_path, cases_path = write_spec_bundle(
                root, make_minimal_spec('L1'), make_minimal_cases(),
            )
            original = json.loads(spec_path.read_text(encoding='utf-8'))
            fields = (
                ('target', 'candidate_revision'),
                ('target', 'candidate_source_tree_hash'),
                ('target', 'candidate_plugin_tree_hash'),
                ('suite', 'cases_content_hash'),
                ('suite', 'case_contracts_content_hash'),
                ('suite', 'fixture_manifest_set_hash'),
                ('suite', 'grader_batch_schedule_hash'),
            )
            for owner, field in fields:
                with self.subTest(field=field):
                    mutated = json.loads(json.dumps(original))
                    mutated[owner].pop(field)
                    spec_path.write_text(json.dumps(mutated), encoding='utf-8')
                    result = self.call_cli(
                        'scripts/validate_eval_suite.py', str(spec_path), str(cases_path),
                    )
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(f'spec.{owner}.{field}', result.stdout)


if __name__ == '__main__':
    unittest.main()  # noqa: F405
