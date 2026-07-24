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
            'sha256': (
                'sha256:'
                + hashlib.sha256(paths['calibration'].read_bytes()).hexdigest()
            ),
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
            registry=validator.load_v5_schema_registry(),
            errors=errors,
            warnings=[],
        )
        return errors

    def test_calibration_producer_recomputes_and_self_hashes_normalized_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
        registry = validator.load_v5_schema_registry()
        self.assertEqual(
            [],
            validator.validate_v5_schema(
                artifact, 'grader-calibration-v1.schema.json', registry,
            ),
        )
        self.assertTrue(
            load_evidence_io_module().verify_self_hash(
                artifact, 'calibration_hash',
            ),
        )
        cell = artifact['metrics']['judge_to_gold'][0]
        self.assertEqual(1.0, cell['agreement'])
        self.assertEqual('independent', artifact['independence']['status'])

    def test_public_calibration_input_templates_produce_normalized_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_calibration_requires_every_selected_model_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
            schedule = {
                'method': 'counterbalanced',
                'seed': 7,
                'schedule_hash': canonical_hash([
                    {
                        'example_id': row['example_id'],
                        'position': index,
                    }
                    for index, row in enumerate(ratings, start=1)
                ]),
            }
            for index, row in enumerate(ratings, start=1):
                row['position'] = index
                row['ordering'] = schedule
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
            paths = materialize_v5_calibration_inputs(Path(tmp))
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

    def test_high_risk_model_calibration_requires_two_human_raters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.human_raters', result.stderr)

    def test_calibration_reviewer_id_has_one_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_calibration_inputs(Path(tmp))
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

    def test_high_risk_calibration_recomputes_human_pair_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
            judge_rows = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            ratings = list(judge_rows)
            for ordinal in (1, 2):
                for source in judge_rows:
                    row = copy.deepcopy(source)
                    row['rating_id'] = (
                        f"human-{ordinal}-{source['example_id']}"
                    )
                    row['reviewer'] = {
                        'reviewer_id': f'human-{ordinal}',
                        'role': 'human',
                        'authority': 'calibration-owner',
                        'principal_id': f'human-principal-{ordinal}',
                        'blinded': True,
                    }
                    ratings.append(row)
            for index, row in enumerate(ratings, start=1):
                row['position'] = index
            ordering = {
                'method': 'counterbalanced',
                'seed': 7,
                'schedule_hash': canonical_hash([
                    {
                        'example_id': row['example_id'],
                        'position': row['position'],
                    }
                    for row in ratings
                ]),
            }
            for row in ratings:
                row['ordering'] = ordering
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
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
        self.assertEqual(3, len(artifact['reviewers']))
        self.assertTrue(artifact['metrics']['human_to_human'])
        self.assertTrue(artifact['metrics']['judge_to_human'])

    def test_grounding_calibration_requires_support_and_attribution_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_calibration_inputs(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['graders'][0]['checks'].append({
                'check_id': 'grounding-check',
                'dimension': 'grounding',
                'required': True,
                'pass_condition': 'Claims have fresh attributed support.',
            })
            validator = load_validator_module()
            spec['suite']['grader_set_hash'] = validator.v5_grader_set_hash(
                spec['graders'],
            )
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
            for label, rating in zip(source_labels, source_ratings):
                bound_label = copy.deepcopy(label)
                bound_label['example_id'] = f"grounding-{label['example_id']}"
                bound_label['dimension'] = 'grounding'
                bound_label['check_id'] = 'grounding-check'
                bound_label['payload_hash'] = canonical_hash({
                    'example_id': bound_label['example_id'],
                })
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
            ordering = {
                'method': 'counterbalanced',
                'seed': 7,
                'schedule_hash': canonical_hash([
                    {
                        'example_id': row['example_id'],
                        'position': row['position'],
                    }
                    for row in ratings
                ]),
            }
            for row in ratings:
                row['ordering'] = ordering
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
                paths = materialize_v5_calibration_inputs(Path(tmp))
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

    def test_calibration_producer_fails_closed_on_expiry_and_scope(self) -> None:
        for mutation, expected in (
            ('expiry', 'calibration.expiry'),
            ('scope', 'calibration.scope'),
        ):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_v5_calibration_inputs(Path(tmp))
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
                    for row in labels:
                        row['task'] = 'unrelated-task'
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
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
            'candidate_evidence_source_hashes': ['candidate-source'],
            'grader_evidence_source_hashes': ['grader-source'],
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
            {'grader_evidence_source_hashes': ['candidate-source']},
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
                paths = materialize_v5_calibration_inputs(Path(tmp))
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
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
            validator = load_validator_module()
            artifact['calibration_hash'] = validator.canonical_self_hash(
                artifact, 'calibration_hash',
            )
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
            paths = materialize_v5_calibration_inputs(Path(tmp))
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
            paths = materialize_v5_contract_fixture(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['suite']['calibration'] = {
                'path': paths['quality'].name,
                'sha256': (
                    'sha256:'
                    + hashlib.sha256(paths['quality'].read_bytes()).hexdigest()
                ),
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
            paths = materialize_v5_calibration_inputs(Path(tmp) / 'calibration')
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

            quality_paths = materialize_v5_suite_quality_input(
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

    def test_suite_quality_producer_recomputes_gates_and_self_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_suite_quality_input(Path(tmp))
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
            validator.validate_v5_schema(
                artifact,
                'suite-quality-v1.schema.json',
                validator.load_v5_schema_registry(),
            ),
        )
        self.assertTrue(
            load_evidence_io_module().verify_self_hash(
                artifact, 'suite_quality_hash',
            ),
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
            output = root / 'generated-suite-quality-v1.json'
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

    def test_suite_quality_excludes_readiness_but_binds_quality_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_suite_quality_input(Path(tmp))
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
            spec['subject']['mechanisms'].append('knowledge_reference')
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )
            bound = self.run_cmd(*command)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(excluded.returncode, 0, excluded.stdout + excluded.stderr)
        self.assertEqual(bound.returncode, 1, bound.stdout + bound.stderr)
        self.assertIn('quality.contract_hash', bound.stdout + bound.stderr)

    def test_contract_recomputes_suite_quality_from_bound_raw_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_suite_quality_input(Path(tmp))
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
            artifact['suite_quality_hash'] = validator.canonical_self_hash(
                artifact, 'suite_quality_hash',
            )
            paths['generated_quality'].write_text(
                json.dumps(artifact, separators=(',', ':')),
                encoding='utf-8',
            )
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['suite']['quality'] = {
                'path': paths['generated_quality'].name,
                'sha256': (
                    'sha256:'
                    + hashlib.sha256(
                        paths['generated_quality'].read_bytes(),
                    ).hexdigest()
                ),
            }
            errors: list[dict[str, str]] = []
            validator._validate_quality_binding(
                spec,
                spec_path=paths['spec'],
                ready=True,
                registry=validator.load_v5_schema_registry(),
                calibration=None,
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
            paths = materialize_v5_suite_quality_input(Path(tmp))
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
            paths = materialize_v5_suite_quality_input(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['subject']['mechanisms'].append('security_sensitive')
            for decision in spec['applicability']:
                if decision['module'] == 'dynamic_security':
                    decision['status'] = 'required'
                    decision['reason'] = 'security behavior is in scope'
            validator = load_validator_module()
            spec['suite']['quality_contract_hash'] = (
                validator.quality_contract_hash(spec)
            )
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
                paths = materialize_v5_suite_quality_input(Path(tmp))
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
        examples = make_v5_schema_examples()
        spec = examples['eval-spec-v5.schema.json']
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
            deterministic = materialize_v5_suite_quality_input(
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
                'sha256': 'sha256:' + hashlib.sha256(
                    deterministic['generated_quality'].read_bytes(),
                ).hexdigest(),
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

            model = materialize_v5_calibration_inputs(root / 'model')
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
                'sha256': 'sha256:' + hashlib.sha256(
                    model['calibration'].read_bytes(),
                ).hexdigest(),
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
            model_quality = root / 'model' / 'generated-suite-quality-v1.json'
            model_proof = root / 'model' / 'suite-quality-proof.json'
            model_spec['suite']['quality'] = {
                'path': model_quality.name,
                'sha256': 'sha256:' + '0' * 64,
            }
            validator = load_validator_module()
            model_spec['suite']['quality_contract_hash'] = (
                validator.quality_contract_hash(model_spec)
            )
            model['spec'].write_text(
                json.dumps(model_spec, indent=2) + '\n', encoding='utf-8',
            )
            proof_source = materialize_v5_suite_quality_input(
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
            proof['custody']['split_hashes'] = validator._quality_split_hashes(
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
            model_spec['suite']['quality']['sha256'] = (
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
