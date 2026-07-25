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

    def _materialize_high_risk_reviewer_pair(
        self,
        root: Path,
    ) -> dict[str, Path]:
        paths = materialize_v5_calibration_inputs(root)
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
        return materialize_v5_reviewer_pair(paths)

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

    def _close_self_hash(self, value: dict, field: str) -> None:
        value[field] = canonical_hash({
            key: item for key, item in value.items() if key != field
        })

    def _rebind_pair(self, paths: dict[str, Path]) -> None:
        pair = json.loads(paths['reviewer_pair'].read_text(encoding='utf-8'))
        for field, path_key in (
            ('packet', 'reviewer_packet'),
            ('output_schema', 'reviewer_schema'),
            ('sealed_mapping', 'reviewer_mapping'),
        ):
            pair[field]['sha256'] = (
                'sha256:' + hashlib.sha256(paths[path_key].read_bytes()).hexdigest()
            )
        for binding, ordinal in zip(
            pair['reviewer_receipts'], (1, 2), strict=True,
        ):
            receipt = paths[f'reviewer_{ordinal}'] / 'receipt.json'
            binding['sha256'] = (
                'sha256:' + hashlib.sha256(receipt.read_bytes()).hexdigest()
            )
        self._close_self_hash(pair, 'pair_hash')
        self._write_json(paths['reviewer_pair'], pair)

    def _close_receipt(
        self,
        paths: dict[str, Path],
        ordinal: int,
    ) -> None:
        receipt_path = paths[f'reviewer_{ordinal}'] / 'receipt.json'
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        self._close_self_hash(receipt, 'receipt_hash')
        self._write_json(receipt_path, receipt)
        self._rebind_pair(paths)

    def _rebind_reviewer_graph(self, paths: dict[str, Path]) -> None:
        packet = json.loads(paths['reviewer_packet'].read_text(encoding='utf-8'))
        output_schema = json.loads(
            paths['reviewer_schema'].read_text(encoding='utf-8'),
        )
        packet_sha = (
            'sha256:' + hashlib.sha256(
                paths['reviewer_packet'].read_bytes(),
            ).hexdigest()
        )
        schema_sha = (
            'sha256:' + hashlib.sha256(
                paths['reviewer_schema'].read_bytes(),
            ).hexdigest()
        )
        mapping = json.loads(
            paths['reviewer_mapping'].read_text(encoding='utf-8'),
        )
        mapping['packet_hash'] = packet_sha
        mapping['output_schema_hash'] = schema_sha
        self._close_self_hash(mapping, 'mapping_hash')
        self._write_json(paths['reviewer_mapping'], mapping)
        for ordinal in (1, 2):
            reviewer = paths[f'reviewer_{ordinal}']
            prompt_path = reviewer / 'prompt.json'
            prompt = json.loads(prompt_path.read_text(encoding='utf-8'))
            prompt['packet'] = packet
            prompt['output_schema'] = output_schema
            self._write_json(prompt_path, prompt)
            prompt_sha = (
                'sha256:' + hashlib.sha256(prompt_path.read_bytes()).hexdigest()
            )
            spawn_path = reviewer / 'spawn-request.json'
            spawn = json.loads(spawn_path.read_text(encoding='utf-8'))
            spawn['message_hash'] = prompt_sha
            self._write_json(spawn_path, spawn)
            response_path = reviewer / 'raw-response.json'
            response = json.loads(response_path.read_text(encoding='utf-8'))
            response_sha = (
                'sha256:' + hashlib.sha256(response_path.read_bytes()).hexdigest()
            )
            terminal_path = reviewer / 'terminal-result.json'
            terminal = json.loads(terminal_path.read_text(encoding='utf-8'))
            terminal['raw_response_hash'] = response_sha
            self._write_json(terminal_path, terminal)
            receipt_path = reviewer / 'receipt.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            receipt.update({
                'reservation_hash': (
                    'sha256:' + hashlib.sha256(
                        (reviewer / 'reservation.json').read_bytes(),
                    ).hexdigest()
                ),
                'prompt_hash': prompt_sha,
                'packet_hash': packet_sha,
                'output_schema_hash': schema_sha,
                'spawn_request_hash': (
                    'sha256:' + hashlib.sha256(spawn_path.read_bytes()).hexdigest()
                ),
                'spawn_ack_hash': (
                    'sha256:' + hashlib.sha256(
                        (reviewer / 'spawn-ack.json').read_bytes(),
                    ).hexdigest()
                ),
                'terminal_result_hash': (
                    'sha256:' + hashlib.sha256(
                        terminal_path.read_bytes(),
                    ).hexdigest()
                ),
                'raw_response_hash': response_sha,
                'parsed_ratings_hash': canonical_hash(response['ratings']),
            })
            self._close_self_hash(receipt, 'receipt_hash')
            self._write_json(receipt_path, receipt)
        self._rebind_pair(paths)

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
        self.assertIsNone(artifact['reviewer_pair'])
        self.assertIsNone(artifact['metrics']['reviewer_to_reviewer'])
        self.assertEqual([], artifact['metrics']['judge_to_reviewer'])

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

    def test_high_risk_model_calibration_requires_reviewer_pair(self) -> None:
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
        self.assertIn('calibration.reviewer_pair_required', result.stderr)

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

    def test_high_risk_calibration_recomputes_reviewer_pair_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
        self.assertEqual(3, len(artifact['reviewers']))
        self.assertTrue(artifact['metrics']['reviewer_to_reviewer'])
        self.assertTrue(artifact['metrics']['judge_to_reviewer'])
        self.assertEqual(
            paths['reviewer_pair'].relative_to(paths['calibration'].parent).as_posix(),
            artifact['reviewer_pair']['path'],
        )

    def test_reviewer_packet_binds_blinded_semantic_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            packet = json.loads(
                paths['reviewer_packet'].read_text(encoding='utf-8'),
            )
            for example in packet['examples']:
                payload = example['payload']
                self.assertEqual({'view', 'check'}, set(payload))
                self.assertTrue(payload['view'])
                self.assertEqual(
                    {'check_id', 'pass_condition'}, set(payload['check']),
                )
                self.assertTrue(payload['check']['pass_condition'].strip())
                self.assertEqual(
                    canonical_hash(payload), example['payload_hash'],
                )

        forbidden_keys = (
            'gold_label',
            'gold_severity',
            'expected_overall',
            'expected_checks',
            'judge_output',
            'other_reviewer_output',
            'plan',
            'source_path',
            'filesystem_locator',
        )
        for forbidden_key in (None, *forbidden_keys):
            tamper = (
                'unbound-view'
                if forbidden_key is None
                else f'forbidden-{forbidden_key}'
            )
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                packet = json.loads(
                    paths['reviewer_packet'].read_text(encoding='utf-8'),
                )
                payload = packet['examples'][0]['payload']
                if forbidden_key is None:
                    payload['view']['candidate_evidence'] = 'tampered'
                else:
                    payload['view'][forbidden_key] = 'forbidden'
                    packet['examples'][0]['payload_hash'] = canonical_hash(payload)
                self._close_self_hash(packet, 'packet_hash')
                self._write_json(paths['reviewer_packet'], packet)
                self._rebind_reviewer_graph(paths)
                result = self._run_pair_calibration(paths)
                self.assertEqual(
                    1, result.returncode, result.stdout + result.stderr,
                )
                self.assertIn('calibration.reviewer_packet', result.stderr)

    def test_reviewer_packet_pass_condition_is_spec_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            packet = json.loads(
                paths['reviewer_packet'].read_text(encoding='utf-8'),
            )
            payload = packet['examples'][0]['payload']
            payload['check']['pass_condition'] = 'Tampered condition.'
            payload_hash = canonical_hash(payload)
            packet['examples'][0]['payload_hash'] = payload_hash
            self._close_self_hash(packet, 'packet_hash')
            self._write_json(paths['reviewer_packet'], packet)

            mapping = json.loads(
                paths['reviewer_mapping'].read_text(encoding='utf-8'),
            )
            mapping['examples'][0]['payload_hash'] = payload_hash
            self._close_self_hash(mapping, 'mapping_hash')
            self._write_json(paths['reviewer_mapping'], mapping)
            example_id = mapping['examples'][0]['example_id']
            labels = [
                json.loads(line)
                for line in paths['labels'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            next(
                row for row in labels if row['example_id'] == example_id
            )['payload_hash'] = payload_hash
            paths['labels'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in labels
                ),
                encoding='utf-8',
            )
            self._rebind_reviewer_graph(paths)
            result = self._run_pair_calibration(paths)
            self.assertEqual(
                1, result.returncode, result.stdout + result.stderr,
            )
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
            reviewer_row['label'] = 'fail'
            reviewer_row['severity'] = 3
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            response_path = paths['reviewer_2'] / 'raw-response.json'
            response = json.loads(response_path.read_text(encoding='utf-8'))
            response['ratings'][0]['label'] = 'fail'
            response['ratings'][0]['severity'] = 3
            self._write_json(response_path, response)
            self._rebind_reviewer_graph(paths)
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
        self.assertEqual(0.75, reviewer_cell['agreement'])
        self.assertEqual(0.75, reviewer_cell['severity_error'])
        self.assertEqual(0.75, judge_cell['agreement'])
        self.assertEqual(0.375, judge_cell['severity_error'])
        self.assertEqual(0, judge_cell['confusion']['false_positive'])
        self.assertEqual(0, judge_cell['confusion']['false_negative'])

    def test_calibration_schema_rejects_legacy_human_semantics(self) -> None:
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
        validator = load_validator_module()
        registry = validator.load_v5_schema_registry()
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
                    validator.validate_v5_schema(
                        legacy,
                        'grader-calibration-v1.schema.json',
                        registry,
                    ),
                )

    def test_reviewer_pair_rejects_cardinality_and_identity_collisions(self) -> None:
        mutations = (
            ('missing_pair', 'calibration.reviewer_pair_missing'),
            ('single_reviewer', 'calibration.reviewer_count'),
            ('third_reviewer', 'calibration.reviewer_count'),
            ('duplicate_reviewer', 'calibration.reviewer_identity'),
            ('duplicate_principal', 'calibration.reviewer_identity'),
            ('duplicate_request', 'calibration.reviewer_identity'),
            ('judge_reviewer_collision', 'calibration.reviewer_identity'),
            ('judge_principal_collision', 'calibration.reviewer_identity'),
            ('reviewer_judge_identity', 'calibration.ratings_shape'),
        )
        for mutation, expected in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                ratings = [
                    json.loads(line)
                    for line in paths['ratings'].read_text(
                        encoding='utf-8',
                    ).splitlines()
                ]
                if mutation == 'missing_pair':
                    result = self.run_cmd(
                        'scripts/validate_eval_suite.py', 'calibration',
                        '--spec', str(paths['spec']),
                        '--ratings', str(paths['ratings']),
                        '--labels', str(paths['labels']),
                        '--output', str(paths['calibration']),
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(expected, result.stderr)
                    continue
                if mutation == 'single_reviewer':
                    ratings = [
                        row for row in ratings
                        if row['reviewer']['reviewer_id'] != 'reviewer-2'
                    ]
                elif mutation == 'third_reviewer':
                    source = copy.deepcopy(ratings[-1])
                    source['rating_id'] = 'reviewer-3-extra'
                    source['reviewer']['reviewer_id'] = 'reviewer-3'
                    source['reviewer']['principal_id'] = 'reviewer-principal-3'
                    ratings.append(source)
                elif mutation == 'duplicate_reviewer':
                    for row in ratings:
                        if row['reviewer']['reviewer_id'] == 'reviewer-2':
                            row['reviewer']['reviewer_id'] = 'reviewer-1'
                elif mutation == 'duplicate_principal':
                    for row in ratings:
                        if row['reviewer']['reviewer_id'] == 'reviewer-2':
                            row['reviewer']['principal_id'] = (
                                'reviewer-principal-1'
                            )
                    receipt_path = paths['reviewer_2'] / 'receipt.json'
                    receipt = json.loads(
                        receipt_path.read_text(encoding='utf-8'),
                    )
                    receipt['principal_id'] = 'reviewer-principal-1'
                    self._write_json(receipt_path, receipt)
                    self._close_receipt(paths, 2)
                elif mutation == 'duplicate_request':
                    for name in (
                        'reservation.json',
                        'spawn-request.json',
                        'spawn-ack.json',
                        'terminal-result.json',
                    ):
                        path = paths['reviewer_2'] / name
                        value = json.loads(path.read_text(encoding='utf-8'))
                        value['request_id'] = 'reviewer-request-1'
                        self._write_json(path, value)
                    receipt_path = paths['reviewer_2'] / 'receipt.json'
                    receipt = json.loads(
                        receipt_path.read_text(encoding='utf-8'),
                    )
                    receipt['request_id'] = 'reviewer-request-1'
                    self._write_json(receipt_path, receipt)
                    self._rebind_reviewer_graph(paths)
                elif mutation == 'judge_reviewer_collision':
                    for row in ratings:
                        if row['reviewer']['role'] == 'judge':
                            row['reviewer']['reviewer_id'] = 'reviewer-1'
                elif mutation == 'judge_principal_collision':
                    for row in ratings:
                        if row['reviewer']['role'] == 'judge':
                            row['reviewer']['principal_id'] = (
                                'reviewer-principal-1'
                            )
                elif mutation == 'reviewer_judge_identity':
                    judge_identity = next(
                        row['grader_identity']
                        for row in ratings
                        if row['reviewer']['role'] == 'judge'
                    )
                    next(
                        row for row in ratings
                        if row['reviewer']['reviewer_id'] == 'reviewer-1'
                    )['grader_identity'] = copy.deepcopy(judge_identity)
                paths['ratings'].write_text(
                    ''.join(
                        json.dumps(row, separators=(',', ':')) + '\n'
                        for row in ratings
                    ),
                    encoding='utf-8',
                )
                result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(expected, result.stderr)

    def test_reviewer_pair_rejects_requested_configuration_tamper(self) -> None:
        for field, value in (
            ('model', 'gpt-5.6-terra'),
            ('reasoning_effort', 'high'),
            ('service_tier', 'standard'),
            ('fork_turns', 'all'),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                receipt_path = paths['reviewer_1'] / 'receipt.json'
                receipt = json.loads(
                    receipt_path.read_text(encoding='utf-8'),
                )
                receipt['requested_configuration'][field] = value
                self._write_json(receipt_path, receipt)
                self._close_receipt(paths, 1)
                result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('calibration.reviewer_receipt', result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            spawn_path = paths['reviewer_1'] / 'spawn-request.json'
            spawn = json.loads(spawn_path.read_text(encoding='utf-8'))
            spawn['model'] = 'gpt-5.6-terra'
            self._write_json(spawn_path, spawn)
            self._rebind_reviewer_graph(paths)
            result = self._run_pair_calibration(paths)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.reviewer_spawn_request', result.stderr)

    def test_reviewer_pair_rejects_barrier_and_observable_extra_events(self) -> None:
        mutations = (
            ('barrier', 'result_consumed_sequence', 2, 'calibration.reviewer_barrier'),
            ('extra_turn', 'observable_extra_turns', 1, 'calibration.reviewer_terminal'),
            (
                'non_integer_turn',
                'observable_extra_turns',
                False,
                'calibration.reviewer_terminal',
            ),
            ('followup', 'observable_followups', 1, 'calibration.reviewer_terminal'),
            (
                'tool_event',
                'observable_tool_events',
                ['observed-tool-event'],
                'calibration.reviewer_terminal',
            ),
        )
        for name, field, value, expected in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                terminal_path = paths['reviewer_1'] / 'terminal-result.json'
                terminal = json.loads(
                    terminal_path.read_text(encoding='utf-8'),
                )
                terminal[field] = value
                self._write_json(terminal_path, terminal)
                self._rebind_reviewer_graph(paths)
                result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(expected, result.stderr)

    def test_reviewer_pair_rejects_output_coverage_and_parsed_hash_tamper(self) -> None:
        for mutation in ('truncated', 'schema_invalid'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                response_path = paths['reviewer_1'] / 'raw-response.json'
                response_path.write_text(
                    '{' if mutation == 'truncated' else '{}\n',
                    encoding='utf-8',
                )
                response_sha = (
                    'sha256:' + hashlib.sha256(
                        response_path.read_bytes(),
                    ).hexdigest()
                )
                terminal_path = paths['reviewer_1'] / 'terminal-result.json'
                terminal = json.loads(
                    terminal_path.read_text(encoding='utf-8'),
                )
                terminal['raw_response_hash'] = response_sha
                self._write_json(terminal_path, terminal)
                receipt_path = paths['reviewer_1'] / 'receipt.json'
                receipt = json.loads(
                    receipt_path.read_text(encoding='utf-8'),
                )
                receipt['raw_response_hash'] = response_sha
                receipt['terminal_result_hash'] = (
                    'sha256:' + hashlib.sha256(
                        terminal_path.read_bytes(),
                    ).hexdigest()
                )
                self._write_json(receipt_path, receipt)
                self._close_receipt(paths, 1)
                result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('calibration.reviewer_output', result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            ratings = [
                json.loads(line)
                for line in paths['ratings'].read_text(
                    encoding='utf-8',
                ).splitlines()
            ]
            removed = next(
                index for index, row in enumerate(ratings)
                if row['reviewer']['reviewer_id'] == 'reviewer-1'
            )
            ratings.pop(removed)
            paths['ratings'].write_text(
                ''.join(
                    json.dumps(row, separators=(',', ':')) + '\n'
                    for row in ratings
                ),
                encoding='utf-8',
            )
            response_path = paths['reviewer_1'] / 'raw-response.json'
            response = json.loads(response_path.read_text(encoding='utf-8'))
            response['ratings'].pop(0)
            self._write_json(response_path, response)
            self._rebind_reviewer_graph(paths)
            coverage = self._run_pair_calibration(paths)
        self.assertEqual(coverage.returncode, 1, coverage.stdout + coverage.stderr)
        self.assertIn('calibration.reviewer_coverage', coverage.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            receipt_path = paths['reviewer_1'] / 'receipt.json'
            receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
            receipt['parsed_ratings_hash'] = 'sha256:' + '0' * 64
            self._write_json(receipt_path, receipt)
            self._close_receipt(paths, 1)
            parsed = self._run_pair_calibration(paths)
        self.assertEqual(parsed.returncode, 1, parsed.stdout + parsed.stderr)
        self.assertIn('calibration.reviewer_output', parsed.stderr)

    def test_reviewer_pair_rejects_bound_artifact_tamper(self) -> None:
        mutations = (
            ('pair', 'reviewer_pair', 'calibration.reviewer_pair'),
            ('packet', 'reviewer_packet', 'calibration.reviewer_packet'),
            ('schema', 'reviewer_schema', 'calibration.reviewer_schema'),
            ('mapping', 'reviewer_mapping', 'calibration.reviewer_mapping'),
            (
                'receipt',
                'reviewer_1/receipt.json',
                'calibration.reviewer_receipt',
            ),
            (
                'spawn_request',
                'reviewer_1/spawn-request.json',
                'calibration.reviewer_spawn_request',
            ),
            (
                'spawn_ack',
                'reviewer_1/spawn-ack.json',
                'calibration.reviewer_spawn_ack',
            ),
        )
        for name, locator, expected in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                if '/' in locator:
                    root_key, relative = locator.split('/', 1)
                    path = paths[root_key] / relative
                else:
                    path = paths[locator]
                if name == 'pair':
                    pair = json.loads(path.read_text(encoding='utf-8'))
                    pair['pair_id'] = 'tampered-pair'
                    self._write_json(path, pair)
                else:
                    path.write_bytes(path.read_bytes() + b' ')
                result = self._run_pair_calibration(paths)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(expected, result.stderr)

    def test_calibration_pair_ratings_and_labels_reject_unsafe_paths(self) -> None:
        for field in ('reviewer_pair', 'ratings', 'labels'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                original = paths[field]
                target = original.with_name(original.name + '.real')
                original.rename(target)
                original.symlink_to(target.name)
                result = self._run_pair_calibration(paths)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('symlink', result.stdout + result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            pair_root = paths['reviewer_pair'].parent
            real_root = pair_root.with_name('reviewer-pair-real')
            pair_root.rename(real_root)
            pair_root.symlink_to(real_root.name, target_is_directory=True)
            result = self._run_pair_calibration(paths)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('symlink', result.stdout + result.stderr)

        for field in ('reviewer_pair', 'ratings', 'labels'):
            with (
                self.subTest(field=f'outside-{field}'),
                tempfile.TemporaryDirectory() as tmp,
                tempfile.TemporaryDirectory() as outside,
            ):
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                external = Path(outside) / paths[field].name
                external.write_bytes(paths[field].read_bytes())
                paths[field] = external
                result = self._run_pair_calibration(paths)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('outside output root', result.stdout + result.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            paths['reviewer_pair'] = paths['reviewer_1']
            result = self._run_pair_calibration(paths)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('calibration.artifact_path', result.stderr)

    def test_calibration_recomputes_pair_binding_and_self_hash(self) -> None:
        for mutation in ('binding', 'metrics'):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as tmp,
            ):
                paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
                produced = self._run_pair_calibration(paths)
                self.assertEqual(
                    produced.returncode, 0, produced.stdout + produced.stderr,
                )
                artifact = json.loads(
                    paths['calibration'].read_text(encoding='utf-8'),
                )
                if mutation == 'binding':
                    artifact['reviewer_pair']['sha256'] = 'sha256:' + '0' * 64
                else:
                    artifact['metrics']['reviewer_to_reviewer'][0][
                        'agreement'
                    ] = 0.25
                artifact['calibration_hash'] = canonical_hash({
                    key: value
                    for key, value in artifact.items()
                    if key != 'calibration_hash'
                })
                self._write_json(paths['calibration'], artifact)
                normalization_errors = self._calibration_binding_errors(paths)
            self.assertIn(
                'calibration.normalization',
                {error['code'] for error in normalization_errors},
                normalization_errors,
            )

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._materialize_high_risk_reviewer_pair(Path(tmp))
            produced = self._run_pair_calibration(paths)
            self.assertEqual(
                produced.returncode, 0, produced.stdout + produced.stderr,
            )
            artifact = json.loads(
                paths['calibration'].read_text(encoding='utf-8'),
            )
            artifact['calibration_hash'] = 'sha256:' + '0' * 64
            self._write_json(paths['calibration'], artifact)
            self_hash_errors = self._calibration_binding_errors(paths)
        self.assertIn(
            'self_hash.mismatch',
            {error['code'] for error in self_hash_errors},
            self_hash_errors,
        )

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
