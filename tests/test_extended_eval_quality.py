from __future__ import annotations

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedEvalQuality(SkillEvaluatorTestCase):  # noqa: F405
    def _calibration_binding_errors(
        self,
        paths: dict[str, Path],
        *,
        require_independent: bool = False,
    ) -> list[dict[str, str]]:
        validator = load_validator_module()
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        spec['suite']['calibration'] = {
            'path': paths['calibration'].name,
            'digest': (
                'sha256:'
                + hashlib.sha256(paths['calibration'].read_bytes()).hexdigest()
            ),
            'schema_version': 'grader-calibration/3',
        }
        if require_independent:
            spec['hard_gates'].append({
                'gate_id': 'independent-judge',
                'kind': 'calibration',
                'metric': 'independent_judge',
                'direction': 'equal',
                'threshold': True,
                'authority': 'evaluation-owner',
                'required': True,
            })
        errors: list[dict[str, str]] = []
        validator._validate_calibration_binding(
            spec,
            [
                json.loads(line)
                for line in paths['scenarios'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ],
            json.loads(paths['host'].read_text(encoding='utf-8')),
            spec_path=paths['spec'],
            ready=True,
            registry=validator.load_epoch6_schema_registry(),
            errors=errors,
            warnings=[],
        )
        return errors

    def _materialize_high_risk_reviewer_pair(
        self,
        root: Path,
        *,
        requested_configuration: dict[str, str] | None = None,
    ) -> dict[str, Path]:
        paths = materialize_epoch6_calibration_inputs(root)
        spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
        spec['risk_tier'] = 'high'
        paths['spec'].write_text(
            json.dumps(spec, indent=2) + '\n', encoding='utf-8',
        )
        labels = [
            json.loads(line)
            for line in paths['labels'].read_text(encoding='utf-8').splitlines()
        ]
        for row in labels:
            row['risk'] = 'high'
        paths['labels'].write_text(
            ''.join(
                json.dumps(row, separators=(',', ':')) + '\n'
                for row in labels
            ),
            encoding='utf-8',
        )
        return materialize_epoch6_reviewer_pair(paths, requested_configuration)

    def _run_pair_calibration(
        self,
        paths: dict[str, Path],
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cmd(
            'scripts/validate_eval_suite.py', 'calibration',
            '--spec', str(paths['spec']),
            '--ratings', str(paths['ratings']),
            '--labels', str(paths['labels']),
            '--reviewer-pair', str(paths['reviewer_pair']),
            '--output', str(paths['calibration']),
        )

    def _write_json(self, path: Path, value: dict) -> None:
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n',
            encoding='utf-8',
        )

    @staticmethod
    def _artifact_digest(path: Path) -> str:
        return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()

    def _rebind_pair(self, paths: dict[str, Path]) -> None:
        pair = json.loads(paths['reviewer_pair'].read_text(encoding='utf-8'))
        root = paths['calibration'].parent
        for field in ('packet', 'sealed_mapping'):
            artifact = root / pair[field]['path']
            pair[field]['digest'] = self._artifact_digest(artifact)
        for binding in pair['reviewer_receipts']:
            receipt = root / binding['path']
            binding['digest'] = self._artifact_digest(receipt)
        self._write_json(paths['reviewer_pair'], pair)

    def _rebind_receipt(
        self,
        paths: dict[str, Path],
        ordinal: int,
    ) -> None:
        receipt_path = paths[f'reviewer_{ordinal}'] / 'receipt.json'
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        root = paths['calibration'].parent
        for field in ('prompt', 'raw_response'):
            artifact = root / receipt[field]['path']
            receipt[field]['digest'] = self._artifact_digest(artifact)
        self._write_json(receipt_path, receipt)
        self._rebind_pair(paths)

    def test_calibration_producer_recomputes_normalized_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            result = self.run_cmd(
                'scripts/validate_eval_suite.py',
                'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = json.loads(paths['calibration'].read_text(encoding='utf-8'))
        validator = load_validator_module()
        registry = validator.load_epoch6_schema_registry()
        self.assertEqual(
            [],
            validator.validate_epoch6_schema(
                artifact, 'grader-calibration-v3.schema.json', registry,
            ),
        )
        self.assertEqual(
            'cal.evaluation-fixture.model-grader',
            artifact['calibration_id'],
        )
        self.assertEqual(
            [artifact['labeled_examples']],
            artifact['execution_profile']['evidence_sources'],
        )
        cell = artifact['metrics']['judge_to_gold'][0]
        self.assertEqual(1.0, cell['agreement'])
        self.assertEqual('independent', artifact['independence']['status'])
        self.assertIsNone(artifact['reviewer_pair'])
        self.assertIsNone(artifact['metrics']['reviewer_to_reviewer'])
        self.assertEqual([], artifact['metrics']['judge_to_reviewer'])
        self.assertEqual(
            {'outcome-check', 'safety-check'},
            {item['check_id'] for item in artifact['check_metrics']},
        )
        for metric in artifact['check_metrics']:
            self.assertEqual(8, metric['judge_sample_count'])
            self.assertEqual(1.0, metric['judge_to_gold_agreement'])
            self.assertEqual(0, metric['reviewer_pair_sample_count'])
            self.assertIsNone(metric['reviewer_to_reviewer_agreement'])
            self.assertIsNone(metric['judge_to_reviewer_agreement'])
        for example in artifact['examples']:
            self.assertEqual(
                canonical_hash(example['payload']),
                example['payload_digest'],
            )

    def test_public_calibration_input_templates_produce_normalized_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            shutil.copy2(
                ROOT / 'templates/calibration-ratings.example.jsonl',
                paths['ratings'],
            )
            shutil.copy2(
                ROOT / 'templates/calibration-gold.example.jsonl',
                paths['labels'],
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            ) if result.returncode == 0 else {}
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            {'host_version', 'prompt_id'},
            {item['field'] for item in artifact['drift_triggers']},
        )

    def test_calibration_requires_every_selected_model_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            labels = [
                json.loads(line)
                for line in paths['labels'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            labels = [
                row for row in labels if row['check_id'] != 'safety-check'
            ]
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            ratings = [
                row for row in ratings if row['check_id'] != 'safety-check'
            ]
            for index, row in enumerate(ratings, start=1):
                row['position'] = index
            paths['labels'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in labels
                ),
                encoding='utf-8',
            )
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.check_coverage', result.stderr)

    def test_calibration_thresholds_are_predeclared_in_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            for row in ratings:
                row['thresholds']['minimum_agreement'] = 0.7
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.threshold_contract', result.stderr)

    def test_calibration_enforces_agreement_for_each_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            safety_check = next(
                check
                for grader in spec['graders']
                for check in grader['checks']
                if check['check_id'] == 'safety-check'
            )
            safety_check['dimension'] = 'outcome'
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            labels = [
                json.loads(line)
                for line in paths['labels'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            for row in labels + ratings:
                if row['check_id'] == 'safety-check':
                    row['dimension'] = 'outcome'
            flipped = [
                row for row in ratings
                if row['check_id'] == 'outcome-check'
                and row['label'] in {'pass', 'fail'}
            ][:2]
            for row in flipped:
                row['label'] = 'fail' if row['label'] == 'pass' else 'pass'
            paths['labels'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in labels
                ),
                encoding='utf-8',
            )
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.threshold_failed', result.stderr)
        self.assertIn('outcome-check', result.stderr)

    def test_calibration_v3_semantic_and_per_check_mutations_fail_closed(
        self,
    ) -> None:
        cases = {
            'gold-pass-condition': 'calibration.payload_binding',
            'view-with-stale-digest': 'calibration.labels_shape',
            'gold-digest': 'calibration.labels_shape',
            'rating-check-mismatch': 'calibration.example_join',
            'duplicate-pair': 'calibration.duplicate_id',
            'sample-count': 'calibration.threshold_failed',
            'class-coverage': 'calibration.class_coverage',
            'risk-coverage': 'calibration.risk_coverage',
            'workspace-path': 'calibration.payload_binding',
            'legacy-v1': 'calibration.labels_shape',
        }
        for mutation, expected in cases.items():
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_epoch6_calibration_inputs(Path(tmp))
                labels = [
                    json.loads(line)
                    for line in paths['labels'].read_text(
                        encoding='utf-8',
                    ).splitlines()
                ]
                ratings = [
                    json.loads(line)
                    for line in paths['ratings'].read_text(
                        encoding='utf-8',
                    ).splitlines()
                ]
                target = labels[0]
                target_rating = next(
                    row for row in ratings
                    if (
                        row['example_id'], row['check_id']
                    ) == (target['example_id'], target['check_id'])
                )
                if mutation == 'gold-pass-condition':
                    target['payload']['check']['pass_condition'] += ' Tampered.'
                    target['payload_digest'] = canonical_hash(target['payload'])
                elif mutation == 'view-with-stale-digest':
                    target['payload']['view']['candidate_evidence'] = 'changed'
                elif mutation == 'gold-digest':
                    target['payload_digest'] = 'sha256:' + '0' * 64
                elif mutation == 'rating-check-mismatch':
                    target_rating['check_id'] = 'unknown-check'
                elif mutation == 'duplicate-pair':
                    labels.append(copy.deepcopy(target))
                elif mutation == 'sample-count':
                    removed = next(
                        row for row in labels
                        if row['check_id'] == 'outcome-check'
                        and row['example_id'].endswith('-2')
                    )
                    labels.remove(removed)
                    ratings[:] = [
                        row for row in ratings
                        if (
                            row['example_id'], row['check_id']
                        ) != (removed['example_id'], removed['check_id'])
                    ]
                elif mutation == 'class-coverage':
                    for row in labels:
                        if (
                            row['check_id'] == 'safety-check'
                            and row['class'] == 'boundary'
                        ):
                            row['class'] = 'known_bad'
                elif mutation == 'risk-coverage':
                    for row in labels:
                        if row['check_id'] == 'safety-check':
                            row['risk'] = 'low'
                elif mutation == 'workspace-path':
                    target['payload']['view']['candidate_evidence'] = (
                        '/private/result.json'
                    )
                    target['payload_digest'] = canonical_hash(target['payload'])
                else:
                    for row in labels + ratings:
                        row['schema_version'] = 1
                for position, row in enumerate(ratings, start=1):
                    row['position'] = position
                paths['labels'].write_text(
                    ''.join(
                        json.dumps(row, separators=(',', ':')) + '\n'
                        for row in labels
                    ),
                    encoding='utf-8',
                )
                paths['ratings'].write_text(
                    ''.join(
                        json.dumps(row, separators=(',', ':')) + '\n'
                        for row in ratings
                    ),
                    encoding='utf-8',
                )
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'calibration',
                    '--spec', str(paths['spec']),
                    '--ratings', str(paths['ratings']),
                    '--labels', str(paths['labels']),
                    '--output', str(paths['calibration']),
                )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(expected, result.stderr)

    def test_calibration_v1_artifact_is_explicitly_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_model_ready_fixture(Path(tmp))
            calibration = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
            calibration['schema_version'] = 2
            self._write_json(paths['calibration'], calibration)
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['suite']['calibration']['digest'] = (
                'sha256:'
                + hashlib.sha256(paths['calibration'].read_bytes()).hexdigest()
            )
            self._write_json(paths['spec'], spec)
            rebind_epoch6_contract_fixture(paths)
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            'calibration.unsupported_schema',
            {error['code'] for error in json.loads(result.stdout)['errors']},
        )

    def test_high_risk_model_calibration_allows_manual_authority_without_pair(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['risk_tier'] = 'high'
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            labels = [
                json.loads(line)
                for line in paths['labels'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            for row in labels:
                row['risk'] = 'high'
            paths['labels'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in labels
                ),
                encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            ) if result.returncode == 0 else {}
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNone(artifact['reviewer_pair'])
        self.assertEqual([], artifact['metrics']['judge_to_reviewer'])

    def test_calibration_reviewer_id_has_one_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            ratings[0]['reviewer']['principal_id'] = 'different-principal'
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.reviewer_identity', result.stderr)

    def test_high_risk_calibration_recomputes_reviewer_pair_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
            evidence_files = sorted(
                paths['reviewer_pair'].parent.rglob('*.json'),
            )
        self.assertEqual(3, len(artifact['reviewers']))
        self.assertTrue(artifact['metrics']['reviewer_to_reviewer'])
        self.assertTrue(artifact['metrics']['judge_to_reviewer'])
        for metric in artifact['check_metrics']:
            self.assertEqual(8, metric['reviewer_pair_sample_count'])
            self.assertEqual(1.0, metric['reviewer_to_reviewer_agreement'])
            self.assertEqual(1.0, metric['judge_to_reviewer_agreement'])
        self.assertEqual(
            {
                'path', 'digest', 'schema_version',
            },
            set(artifact['reviewer_pair']),
        )
        self.assertEqual(
            'context-clean-subagent-reviewer-pair/3.0',
            artifact['reviewer_pair']['schema_version'],
        )
        self.assertEqual(9, len(evidence_files))

    def test_reviewer_pair_accepts_frozen_alternate_configuration(self) -> None:
        requested = {
            'model': 'alternate-model',
            'reasoning_effort': 'high',
            'service_tier': 'standard',
            'fork_turns': 'none',
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(
                Path(tmp), requested_configuration=requested,
            )
            result = self._run_pair_calibration(paths)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reviewer_packet_is_semantic_and_output_is_value_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            packet = json.loads(
                paths['reviewer_packet'].read_text(encoding='utf-8'),
            )
            prompt = json.loads(
                (paths['reviewer_1'] / 'prompt.json').read_text(
                    encoding='utf-8',
                ),
            )
            response = json.loads(
                (paths['reviewer_1'] / 'raw-response.json').read_text(
                    encoding='utf-8',
                ),
            )
            from reviewer_prompt_contract import expand_prompt_packet

            expanded = expand_prompt_packet(
                prompt['packet'], campaign_id=packet['campaign_id'],
            )
            self.assertEqual(packet, expanded)
            self.assertEqual(
                {'schema_version', 'campaign_id', 'examples'}, set(packet),
            )
            for example in packet['examples']:
                self.assertEqual(
                    {'opaque_example_id', 'payload'}, set(example),
                )
                self.assertEqual({'view', 'check'}, set(example['payload']))
            self.assertTrue(response['ratings'])
            self.assertTrue(all(
                set(judgment) == {'label', 'severity'}
                for judgment in response['ratings']
            ))
            for document in (
                packet,
                prompt,
                response,
                json.loads(
                    paths['reviewer_pair'].read_text(encoding='utf-8'),
                ),
            ):
                keys: list[str] = []

                def collect(value: object) -> None:
                    if isinstance(value, dict):
                        keys.extend(value)
                        for item in value.values():
                            collect(item)
                    elif isinstance(value, list):
                        for item in value:
                            collect(item)

                collect(document)
                self.assertFalse(any(key.endswith('_hash') for key in keys))

    def test_reviewer_packet_pass_condition_is_spec_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            packet = json.loads(
                paths['reviewer_packet'].read_text(encoding='utf-8'),
            )
            packet['examples'][0]['payload']['check']['pass_condition'] += (
                ' Unregistered.'
            )
            self._write_json(paths['reviewer_packet'], packet)
            self._rebind_pair(paths)
            result = self._run_pair_calibration(paths)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn('calibration.reviewer_packet', result.stderr)

    def test_reviewer_pair_disagreement_uses_abstain_consensus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            reviewer_row = next(
                row for row in ratings
                if row['reviewer']['reviewer_id'] == 'reviewer-2'
            )
            reviewer_row.update({'label': 'fail', 'severity': 3})
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            response_path = paths['reviewer_2'] / 'raw-response.json'
            response = json.loads(response_path.read_text(encoding='utf-8'))
            response['ratings'][0] = {'label': 'fail', 'severity': 3}
            self._write_json(response_path, response)
            self._rebind_receipt(paths, 2)
            result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
        reviewer_cell = next(
            cell for cell in artifact['metrics']['reviewer_to_reviewer']
            if cell['dimension'] == 'outcome'
        )
        judge_cell = next(
            cell for cell in artifact['metrics']['judge_to_reviewer']
            if cell['dimension'] == 'outcome'
        )
        self.assertEqual(0.875, reviewer_cell['agreement'])
        self.assertEqual(0.375, reviewer_cell['severity_error'])
        self.assertEqual(0.875, judge_cell['agreement'])
        self.assertEqual(0.1875, judge_cell['severity_error'])

    def test_calibration_schema_rejects_legacy_human_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            produced = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            self.assertEqual(
                produced.returncode, 0, produced.stdout + produced.stderr,
            )
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
        validator = load_validator_module()
        registry = validator.load_epoch6_schema_registry()
        for mutation in ('metrics', 'role'):
            legacy = copy.deepcopy(artifact)
            if mutation == 'metrics':
                metrics = legacy['metrics']
                metrics['human_to_human'] = metrics.pop(
                    'reviewer_to_reviewer',
                )
                metrics['judge_to_human'] = metrics.pop(
                    'judge_to_reviewer',
                )
            else:
                legacy['reviewers'][0]['role'] = 'human'
            with self.subTest(mutation=mutation):
                self.assertTrue(
                    validator.validate_epoch6_schema(
                        legacy,
                        'grader-calibration-v3.schema.json',
                        registry,
                    ),
                )

    def test_reviewer_pair_rejects_cardinality_and_lifecycle_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            pair = json.loads(
                paths['reviewer_pair'].read_text(encoding='utf-8'),
            )
            pair['reviewer_receipts'] = pair['reviewer_receipts'][:1]
            self._write_json(paths['reviewer_pair'], pair)
            result = self._run_pair_calibration(paths)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn('calibration.reviewer_pair', result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            receipt_path = paths['reviewer_2'] / 'receipt.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            receipt['result_consumed_sequence'] = receipt['ack_sequence']
            self._write_json(receipt_path, receipt)
            self._rebind_pair(paths)
            result = self._run_pair_calibration(paths)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn('calibration.reviewer_receipt', result.stderr)

    def test_reviewer_pair_rejects_identity_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            for row in ratings:
                if row['reviewer']['reviewer_id'] == 'reviewer-1':
                    row['reviewer']['principal_id'] = 'judge-principal'
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            receipt_path = paths['reviewer_1'] / 'receipt.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            receipt['principal_id'] = 'judge-principal'
            self._write_json(receipt_path, receipt)
            self._rebind_pair(paths)
            result = self._run_pair_calibration(paths)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn('calibration.reviewer_identity', result.stderr)

    def test_reviewer_pair_distinguishes_byte_and_semantic_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            response_path = paths['reviewer_1'] / 'raw-response.json'
            response = json.loads(response_path.read_text(encoding='utf-8'))
            response['ratings'][0] = {'label': 'fail', 'severity': 1}
            self._write_json(response_path, response)
            result = self._run_pair_calibration(paths)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn('calibration.reviewer_output', result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            response_path = paths['reviewer_1'] / 'raw-response.json'
            response = json.loads(response_path.read_text(encoding='utf-8'))
            response['ratings'][0] = {'label': 'fail', 'severity': 1}
            self._write_json(response_path, response)
            self._rebind_receipt(paths, 1)
            result = self._run_pair_calibration(paths)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn('calibration.reviewer_output', result.stderr)

    def test_reviewer_pair_rejects_legacy_and_unsafe_bindings(self) -> None:
        for mutation in ('legacy', 'unsafe'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                pair = json.loads(
                    paths['reviewer_pair'].read_text(encoding='utf-8'),
                )
                if mutation == 'legacy':
                    pair['schema_version'] = (
                        'context-clean-subagent-reviewer-pair/2.0'
                    )
                else:
                    pair['reviewer_receipts'][0]['path'] = '../receipt.json'
                self._write_json(paths['reviewer_pair'], pair)
                result = self._run_pair_calibration(paths)
                self.assertEqual(
                    1, result.returncode, result.stdout + result.stderr,
                )
                self.assertIn('calibration.reviewer_', result.stderr)

    def test_grounding_calibration_requires_support_and_attribution_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['graders'][0]['checks'].append({
                'check_id': 'grounding-check',
                'dimension': 'grounding',
                'required': True,
                'pass_condition': 'Claims have fresh attributed support.',
            })
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            labels = [
                json.loads(line)
                for line in paths['labels'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            source_labels = [
                row for row in labels if row['check_id'] == 'outcome-check'
            ]
            source_ratings = [
                row for row in ratings if row['check_id'] == 'outcome-check'
            ]
            semantics = load_grader_semantics_module()
            for label, rating in zip(source_labels, source_ratings):
                bound_label = copy.deepcopy(label)
                bound_label['example_id'] = f"grounding-{label['example_id']}"
                bound_label['dimension'] = 'grounding'
                bound_label['check_id'] = 'grounding-check'
                bound_label['payload'] = semantics.semantic_payload(
                    label['payload']['view'],
                    'grounding-check',
                    'Claims have fresh attributed support.',
                )
                bound_label['payload_digest'] = semantics.semantic_payload_hash(
                    bound_label['payload'],
                )
                labels.append(bound_label)
                bound_rating = copy.deepcopy(rating)
                bound_rating['rating_id'] = (
                    f"rating-{bound_label['example_id']}"
                )
                bound_rating['example_id'] = bound_label['example_id']
                bound_rating['dimension'] = 'grounding'
                bound_rating['check_id'] = 'grounding-check'
                ratings.append(bound_rating)
            for index, row in enumerate(ratings, start=1):
                row['position'] = index
            paths['labels'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in labels
                ),
                encoding='utf-8',
            )
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            missing = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            for row, support in zip(
                [row for row in labels if row['check_id'] == 'grounding-check'],
                ('supported', 'unsupported', 'unattributed', 'stale'),
            ):
                row['source_support'] = support
            paths['labels'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in labels
                ),
                encoding='utf-8',
            )
            closed = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn(
            'calibration.grounding_coverage', missing.stdout + missing.stderr,
        )
        self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)

    def test_calibration_producer_fails_closed_on_blinding_and_order_tamper(self) -> None:
        for mutation, expected in (
            ('blinding', 'calibration.blinding'),
            ('ordering', 'calibration.ordering'),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_epoch6_calibration_inputs(Path(tmp))
                ratings = [
                    json.loads(line)
                    for line in paths['ratings'].read_text(
                        encoding='utf-8',
                    ).splitlines()
                ]
                if mutation == 'blinding':
                    ratings[0]['blinded_treatment_labels'] = False
                else:
                    ratings[0]['position'] = 4
                paths['ratings'].write_text(
                    ''.join(
                        json.dumps(row, separators=(',', ':')) + '\n'
                        for row in ratings
                    ),
                    encoding='utf-8',
                )
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py',
                    'calibration',
                    '--spec', str(paths['spec']),
                    '--ratings', str(paths['ratings']),
                    '--labels', str(paths['labels']),
                    '--output', str(paths['calibration']),
                )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(expected, result.stdout + result.stderr)

    def test_calibration_producer_fails_closed_on_expiry_scope_and_labels(self) -> None:
        for mutation, expected in (
            ('expiry', 'calibration.expiry'),
            ('scope', 'calibration.scope'),
            ('labels', 'calibration.check_label_coverage'),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_epoch6_calibration_inputs(Path(tmp))
                if mutation == 'expiry':
                    ratings = [
                        json.loads(line)
                        for line in paths['ratings'].read_text(
                            encoding='utf-8',
                        ).splitlines()
                    ]
                    for row in ratings:
                        row['expires'] = '2025-12-31T00:00:00Z'
                    paths['ratings'].write_text(
                        ''.join(
                            json.dumps(row, separators=(',', ':')) + '\n'
                            for row in ratings
                        ),
                        encoding='utf-8',
                    )
                else:
                    labels = [
                        json.loads(line)
                        for line in paths['labels'].read_text(
                            encoding='utf-8',
                        ).splitlines()
                    ]
                    if mutation == 'scope':
                        for row in labels:
                            row['task'] = 'unrelated-task'
                    else:
                        target_check = labels[0]['check_id']
                        for row in labels:
                            if (
                                row['check_id'] == target_check
                                and row['gold_label'] == 'fail'
                            ):
                                row['gold_label'] = 'pass'
                                row['gold_severity'] = 0
                    paths['labels'].write_text(
                        ''.join(
                            json.dumps(row, separators=(',', ':')) + '\n'
                            for row in labels
                        ),
                        encoding='utf-8',
                    )
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py',
                    'calibration',
                    '--spec', str(paths['spec']),
                    '--ratings', str(paths['ratings']),
                    '--labels', str(paths['labels']),
                    '--output', str(paths['calibration']),
                )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(expected, result.stdout + result.stderr)

    def test_calibration_output_is_idempotent_but_never_overwrites_different_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            command = (
                'scripts/validate_eval_suite.py',
                'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            first = self.run_cmd(*command)
            second = self.run_cmd(*command)
            paths['calibration'].write_text('{}\n', encoding='utf-8')
            conflict = self.run_cmd(*command)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(conflict.returncode, 2, conflict.stdout + conflict.stderr)
        self.assertIn('refusing to overwrite', conflict.stderr)

    def test_independence_is_derived_from_identity_context_and_sources(self) -> None:
        validator = load_validator_module()
        base = {
            'candidate_principal_id': 'candidate',
            'grader_principal_id': 'grader',
            'context_mode': 'fresh',
            'rationale_exposed': False,
            'candidate_model_genealogy': ['candidate-family'],
            'grader_model_genealogy': ['grader-family'],
            'candidate_evidence_source_ids': ['candidate-source'],
            'grader_evidence_source_ids': ['grader-source'],
        }
        self.assertEqual(
            'independent',
            validator._derive_independence(
                base, blinded=True,
            )['status'],
        )
        for mutation in (
            {'grader_principal_id': 'candidate'},
            {'context_mode': 'forked'},
            {'grader_evidence_source_ids': ['candidate-source']},
        ):
            facts = {**base, **mutation}
            with self.subTest(mutation=mutation):
                self.assertEqual(
                    'dependent',
                    validator._derive_independence(
                        facts, blinded=True,
                    )['status'],
                )
        incomplete = dict(base)
        incomplete.pop('grader_principal_id')
        self.assertEqual(
            'unknown',
            validator._derive_independence(
                incomplete, blinded=True,
            )['status'],
        )

    def test_dependent_and_unknown_calibration_cannot_close_independent_gate(self) -> None:
        for status in ('dependent', 'unknown'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_epoch6_calibration_inputs(Path(tmp))
                ratings = [
                    json.loads(line)
                    for line in paths['ratings'].read_text(
                        encoding='utf-8',
                    ).splitlines()
                ]
                for row in ratings:
                    facts = row['independence_facts']
                    if status == 'dependent':
                        facts['grader_principal_id'] = facts[
                            'candidate_principal_id'
                        ]
                    else:
                        facts.pop('grader_principal_id')
                paths['ratings'].write_text(
                    ''.join(
                        json.dumps(row, separators=(',', ':')) + '\n'
                        for row in ratings
                    ),
                    encoding='utf-8',
                )
                produced = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'calibration',
                    '--spec', str(paths['spec']),
                    '--ratings', str(paths['ratings']),
                    '--labels', str(paths['labels']),
                    '--output', str(paths['calibration']),
                )
                self.assertEqual(
                    produced.returncode, 0, produced.stdout + produced.stderr,
                )
                artifact = json.loads(
                    paths['calibration'].read_text(encoding='utf-8'),
                )
                self.assertEqual(status, artifact['independence']['status'])
                errors = self._calibration_binding_errors(
                    paths, require_independent=True,
                )
                self.assertIn(
                    'calibration.independence',
                    {error['code'] for error in errors},
                    errors,
                )

    def test_contract_recomputes_calibration_normalized_fields_from_raw_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            produced = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
            self.assertEqual(
                produced.returncode, 0, produced.stdout + produced.stderr,
            )
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
            artifact['metrics']['judge_to_gold'][0]['agreement'] = 0.25
            paths['calibration'].write_text(
                json.dumps(artifact, separators=(',', ':')),
                encoding='utf-8',
            )
            errors = self._calibration_binding_errors(paths)
        self.assertIn(
            'calibration.normalization',
            {error['code'] for error in errors},
            errors,
        )

    def test_calibration_malformed_numeric_input_fails_with_owned_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp))
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            ratings[0]['severity'] = {'not': 'numeric'}
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.ratings_shape', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_deterministic_only_contract_forbids_calibration_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_contract_fixture(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['suite']['calibration'] = {
                'path': paths['quality'].name,
                'digest': (
                    'sha256:'
                    + hashlib.sha256(paths['quality'].read_bytes()).hexdigest()
                ),
                'schema_version': 'grader-calibration/3',
            }
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertIn(
            'calibration.forbidden',
            {error['code'] for error in report['errors']},
            report,
        )

    def test_preparation_inputs_reject_candidate_scored_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_calibration_inputs(Path(tmp) / 'calibration')
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            ratings[0]['candidate_scored_result'] = {'pass': True}
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            calibration = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(paths['spec']),
                '--ratings', str(paths['ratings']),
                '--labels', str(paths['labels']),
                '--output', str(paths['calibration']),
            )

            quality_paths = materialize_epoch6_suite_quality_input(
                Path(tmp) / 'quality',
            )
            proof = json.loads(
                quality_paths['quality_proof'].read_text(encoding='utf-8'),
            )
            proof['candidate_scored_result'] = {'pass': True}
            quality_paths['quality_proof'].write_text(
                json.dumps(proof, indent=2) + '\n', encoding='utf-8',
            )
            quality = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(quality_paths['spec']),
                '--proof', str(quality_paths['quality_proof']),
                '--output', str(quality_paths['generated_quality']),
            )
        self.assertEqual(
            calibration.returncode, 1, calibration.stdout + calibration.stderr,
        )
        self.assertIn(
            'calibration.ratings_shape',
            calibration.stdout + calibration.stderr,
        )
        self.assertEqual(quality.returncode, 1, quality.stdout + quality.stderr)
        self.assertIn('quality.proof_shape', quality.stdout + quality.stderr)

    def test_suite_quality_producer_recomputes_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_suite_quality_input(Path(tmp))
            result = self.run_cmd(
                'scripts/validate_eval_suite.py',
                'suite-quality',
                '--spec', str(paths['spec']),
                '--proof', str(paths['quality_proof']),
                '--output', str(paths['generated_quality']),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = json.loads(
                paths['generated_quality'].read_text(encoding='utf-8'),
            )
        validator = load_validator_module()
        self.assertEqual(
            [],
            validator.validate_epoch6_schema(
                artifact,
                'suite-quality-v2.schema.json',
                validator.load_epoch6_schema_registry(),
            ),
        )
        self.assertEqual('sq.evaluation-fixture', artifact['suite_quality_id'])
        self.assertTrue(
            all('digest' in binding for binding in artifact['raw_proofs'].values())
        )
        self.assertEqual(
            {'pass'},
            set(artifact['gates'].values()),
        )

    def test_public_suite_quality_input_template_closes_all_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (
                'eval-spec.example.json',
                'scenarios.example.jsonl',
                'suite-quality-proof.example.json',
                'grader-output.schema.json',
            ):
                shutil.copy2(ROOT / 'templates' / name, root / name)
            output = root / 'generated-suite-quality-v2.json'
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(root / 'eval-spec.example.json'),
                '--proof', str(root / 'suite-quality-proof.example.json'),
                '--output', str(output),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = json.loads(output.read_text(encoding='utf-8'))
            proof_path = root / 'suite-quality-proof.example.json'
            proof = json.loads(proof_path.read_text(encoding='utf-8'))
            proof['duplicate_groups'] = []
            proof_path.write_text(
                json.dumps(proof, indent=2) + '\n',
                encoding='utf-8',
            )
            missing_duplicate = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(root / 'eval-spec.example.json'),
                '--proof', str(proof_path),
                '--output', str(root / 'invalid-suite-quality.json'),
            )
        self.assertEqual({'pass'}, set(artifact['gates'].values()))
        self.assertEqual(
            missing_duplicate.returncode,
            1,
            missing_duplicate.stdout + missing_duplicate.stderr,
        )
        self.assertIn(
            'quality.duplicate_recompute',
            missing_duplicate.stdout + missing_duplicate.stderr,
        )

    def test_suite_quality_excludes_retention_but_reads_spec_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_suite_quality_input(Path(tmp))
            command = (
                'scripts/validate_eval_suite.py',
                'suite-quality',
                '--spec', str(paths['spec']),
                '--proof', str(paths['quality_proof']),
                '--output', str(paths['generated_quality']),
            )
            first = self.run_cmd(*command)
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['artifacts']['retention'] = 'changed-excluded-retention'
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )
            excluded = self.run_cmd(*command)
            spec['subject']['claims'].append('review feedback improves quality')
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )
            bound = self.run_cmd(*command)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(excluded.returncode, 0, excluded.stdout + excluded.stderr)
        self.assertEqual(bound.returncode, 1, bound.stdout + bound.stderr)
        self.assertIn('quality.boundary_coverage', bound.stdout + bound.stderr)

    def test_contract_recomputes_suite_quality_from_bound_raw_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_suite_quality_input(Path(tmp))
            produced = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(paths['spec']),
                '--proof', str(paths['quality_proof']),
                '--output', str(paths['generated_quality']),
            )
            self.assertEqual(
                produced.returncode, 0, produced.stdout + produced.stderr,
            )
            artifact = json.loads(
                paths['generated_quality'].read_text(encoding='utf-8'),
            )
            artifact['coverage']['modules']['core_outcome']['positive'] = 99
            validator = load_validator_module()
            paths['generated_quality'].write_text(
                json.dumps(artifact, separators=(',', ':')),
                encoding='utf-8',
            )
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['suite']['quality'] = {
                'path': paths['generated_quality'].name,
                'digest': (
                    'sha256:'
                    + hashlib.sha256(
                        paths['generated_quality'].read_bytes(),
                    ).hexdigest()
                ),
                'schema_version': 'suite-quality/2',
            }
            errors: list[dict[str, str]] = []
            validator._validate_quality_binding(
                spec,
                spec_path=paths['spec'],
                ready=True,
                registry=validator.load_epoch6_schema_registry(),
                errors=errors,
                warnings=[],
            )
        self.assertIn(
            'quality.normalization',
            {error['code'] for error in errors},
            errors,
        )

    def test_suite_quality_fails_when_required_mutation_is_not_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_suite_quality_input(Path(tmp))
            proof = json.loads(
                paths['quality_proof'].read_text(encoding='utf-8'),
            )
            proof['mutations']['detected_ids'] = []
            paths['quality_proof'].write_text(
                json.dumps(proof, indent=2) + '\n', encoding='utf-8',
            )
            result = self.run_cmd(
                'scripts/validate_eval_suite.py',
                'suite-quality',
                '--spec', str(paths['spec']),
                '--proof', str(paths['quality_proof']),
                '--output', str(paths['generated_quality']),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('quality.mutation_detection', result.stdout + result.stderr)

    def test_suite_quality_requires_security_boundary_mechanisms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_epoch6_suite_quality_input(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['subject']['mechanisms'].append('security_sensitive')
            for decision in spec['applicability']:
                if decision['module'] == 'dynamic_security':
                    decision['status'] = 'required'
                    decision['reason'] = 'security behavior is in scope'
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            missing = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(paths['spec']),
                '--proof', str(paths['quality_proof']),
                '--output', str(paths['generated_quality']),
            )
            proof = json.loads(
                paths['quality_proof'].read_text(encoding='utf-8'),
            )
            proof['boundary_coverage'] = [{
                'surface': 'security',
                'case_classes': [
                    'allow',
                    'deny',
                    'allow-with-changes',
                    'backend-model-divergence',
                    'effect-confirmation',
                ],
                'status': 'pass',
            }]
            paths['quality_proof'].write_text(
                json.dumps(proof, indent=2) + '\n',
                encoding='utf-8',
            )
            closed = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(paths['spec']),
                '--proof', str(paths['quality_proof']),
                '--output', str(paths['generated_quality']),
            )
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertIn(
            'quality.boundary_coverage', missing.stdout + missing.stderr,
        )
        self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)

    def test_quality_review_locators_are_bound_and_in_range(self) -> None:
        for mutation in ('leakage-range', 'semantic-review'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_epoch6_suite_quality_input(Path(tmp))
                proof = json.loads(
                    paths['quality_proof'].read_text(encoding='utf-8'),
                )
                if mutation == 'leakage-range':
                    proof['leakage_probes'][0]['locator']['end_line'] = 999
                else:
                    proof['duplicate_groups'].append({
                        'group_id': 'semantic-overlap',
                        'kind': 'semantic',
                        'case_ids': ['case-basic', 'known-bad'],
                        'status': 'reviewed_distinct',
                        'review_locator': None,
                    })
                paths['quality_proof'].write_text(
                    json.dumps(proof, indent=2) + '\n',
                    encoding='utf-8',
                )
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'suite-quality',
                    '--spec', str(paths['spec']),
                    '--proof', str(paths['quality_proof']),
                    '--output', str(paths['generated_quality']),
                )
            self.assertEqual(
                result.returncode, 1, result.stdout + result.stderr,
            )
            self.assertIn(
                'quality.review_locator', result.stdout + result.stderr,
            )

    def test_boundary_registry_selects_coordination_review_and_grounding(self) -> None:
        validator = load_validator_module()
        examples = make_epoch6_schema_examples()
        spec = examples['eval-spec-v6.schema.json']
        scenario = examples['scenario-v1.schema.json']
        spec['subject']['shape'] = 'handoff_graph'
        spec['subject']['principal_mode'] = 'multiple'
        spec['subject']['claims'].append('reviewer-feedback')
        spec['hard_gates'].append({
            'gate_id': 'independent-judge',
            'kind': 'calibration',
            'metric': 'independent_judge',
            'direction': 'equal',
            'threshold': True,
            'authority': 'evaluation-owner',
            'required': True,
        })
        scenario['requirements'][0]['dimension'] = 'grounding'
        scenario['observation_contracts'] = [{'observation_id': 'present'}]
        required = validator._required_quality_boundaries(spec, [scenario])
        self.assertEqual(
            {
                'coordination',
                'review',
                'independence',
                'observation',
                'grounding',
            },
            set(required),
        )
        self.assertIn('partial-join', required['coordination'])
        self.assertIn('harmful-uptake', required['review'])
        self.assertEqual({'dependent', 'unknown'}, required['independence'])
        self.assertIn('correct-stale', required['observation'])
        self.assertIn('source-exists-unsupported', required['grounding'])

    def test_model_and_deterministic_preparation_chains_reach_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deterministic = materialize_epoch6_suite_quality_input(
                root / 'deterministic',
            )
            deterministic_quality = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(deterministic['spec']),
                '--proof', str(deterministic['quality_proof']),
                '--output', str(deterministic['generated_quality']),
            )
            self.assertEqual(
                deterministic_quality.returncode,
                0,
                deterministic_quality.stdout + deterministic_quality.stderr,
            )
            deterministic_spec = json.loads(
                deterministic['spec'].read_text(encoding='utf-8'),
            )
            deterministic_spec['suite']['quality'] = {
                'path': deterministic['generated_quality'].name,
                'digest': 'sha256:' + hashlib.sha256(
                    deterministic['generated_quality'].read_bytes(),
                ).hexdigest(),
                'schema_version': 'suite-quality/2',
            }
            deterministic_spec['execution']['ready'] = True
            deterministic['spec'].write_text(
                json.dumps(deterministic_spec, indent=2) + '\n',
                encoding='utf-8',
            )
            deterministic_contract = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(deterministic['spec']),
                str(deterministic['scenarios']),
                str(deterministic['host']),
            )

            model = materialize_epoch6_calibration_inputs(root / 'model')
            calibration = self.run_cmd(
                'scripts/validate_eval_suite.py', 'calibration',
                '--spec', str(model['spec']),
                '--ratings', str(model['ratings']),
                '--labels', str(model['labels']),
                '--output', str(model['calibration']),
            )
            self.assertEqual(
                calibration.returncode, 0, calibration.stdout + calibration.stderr,
            )
            model_spec = json.loads(model['spec'].read_text(encoding='utf-8'))
            model_spec['suite']['calibration'] = {
                'path': model['calibration'].name,
                'digest': 'sha256:' + hashlib.sha256(
                    model['calibration'].read_bytes(),
                ).hexdigest(),
                'schema_version': 'grader-calibration/3',
            }
            model_spec['hard_gates'].append({
                'gate_id': 'independent-judge',
                'kind': 'calibration',
                'metric': 'independent_judge',
                'direction': 'equal',
                'threshold': True,
                'authority': 'evaluation-owner',
                'required': True,
            })
            model_quality = root / 'model' / 'generated-suite-quality-v2.json'
            model_proof = root / 'model' / 'suite-quality-proof.json'
            model_spec['suite']['quality'] = {
                'path': model_quality.name,
                'digest': 'sha256:' + '0' * 64,
                'schema_version': 'suite-quality/2',
            }
            validator = load_validator_module()
            model['spec'].write_text(
                json.dumps(model_spec, indent=2) + '\n', encoding='utf-8',
            )
            proof_source = materialize_epoch6_suite_quality_input(
                root / 'proof-source',
            )
            proof = json.loads(
                proof_source['quality_proof'].read_text(encoding='utf-8'),
            )
            model_scenarios = [
                json.loads(line)
                for line in model['scenarios'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            proof['custody']['split_bindings'] = validator._quality_split_bindings(
                model_spec, model_scenarios,
            )
            proof['boundary_coverage'] = [
                {
                    'surface': surface,
                    'case_classes': sorted(case_classes),
                    'status': 'pass',
                }
                for surface, case_classes in sorted(
                    validator._required_quality_boundaries(
                        model_spec, model_scenarios,
                    ).items(),
                )
            ]
            model_proof.write_text(
                json.dumps(proof, indent=2) + '\n', encoding='utf-8',
            )
            quality = self.run_cmd(
                'scripts/validate_eval_suite.py', 'suite-quality',
                '--spec', str(model['spec']),
                '--proof', str(model_proof),
                '--output', str(model_quality),
            )
            self.assertEqual(quality.returncode, 0, quality.stdout + quality.stderr)
            model_spec['suite']['quality']['digest'] = (
                'sha256:' + hashlib.sha256(model_quality.read_bytes()).hexdigest()
            )
            model_spec['execution']['ready'] = True
            model['spec'].write_text(
                json.dumps(model_spec, indent=2) + '\n', encoding='utf-8',
            )
            model_contract = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(model['spec']), str(model['scenarios']), str(model['host']),
            )
        self.assertEqual(
            deterministic_contract.returncode,
            0,
            deterministic_contract.stdout + deterministic_contract.stderr,
        )
        self.assertEqual(
            model_contract.returncode,
            0,
            model_contract.stdout + model_contract.stderr,
        )


if __name__ == '__main__':
    unittest.main()
