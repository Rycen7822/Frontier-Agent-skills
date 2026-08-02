from __future__ import annotations

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedEvalSpec(SkillEvaluatorTestCase):  # noqa: F405
    def test_v5_contract_schemas_are_complete_draft_2020_12_owners(self) -> None:
        self.assertIsNotNone(jsonschema)
        schema_dir = ROOT / 'schemas'
        expected = {
            'eval-spec-v5.schema.json',
            'scenario-v1.schema.json',
            'execution-plan-v1.schema.json',
            'host-manifest-v1.schema.json',
            'run-index-row-v2.schema.json',
            'receipt-v4.schema.json',
            'grader-calibration-v2.schema.json',
            'suite-quality-v1.schema.json',
            'analysis-summary-v4.schema.json',
            'failure-index-v1.schema.json',
            'comparison-plan-v1.schema.json',
            'comparison-observations-v1.schema.json',
            'comparison-report-v1.schema.json',
            'comparison-diagnostic-index-v1.schema.json',
        }
        self.assertEqual(
            {path.name for path in schema_dir.glob('*.schema.json')},
            expected,
        )
        for name in sorted(expected):
            with self.subTest(schema=name):
                schema = json.loads((schema_dir / name).read_text(encoding='utf-8'))
                self.assertEqual(
                    schema['$schema'],
                    'https://json-schema.org/draft/2020-12/schema',
                )
                self.assertEqual(
                    schema['$id'],
                    f'https://example.invalid/skill-evaluator/schemas/{name}',
                )
                self.assertIs(schema['additionalProperties'], False)
                jsonschema.Draft202012Validator.check_schema(schema)

    def test_v5_schema_registry_accepts_positive_examples_and_rejects_owner_mutations(self) -> None:
        from referencing import Registry, Resource
        from urllib.parse import unquote, urljoin, urlsplit

        schema_dir = ROOT / 'schemas'
        schemas = {
            path.name: json.loads(path.read_text(encoding='utf-8'))
            for path in schema_dir.glob('*.schema.json')
        }
        registry = Registry().with_resources(
            (schema['$id'], Resource.from_contents(schema))
            for schema in schemas.values()
        )
        examples = make_v5_schema_examples()
        self.assertEqual(set(examples), set(schemas))

        for name, example in examples.items():
            validator = jsonschema.Draft202012Validator(
                schemas[name],
                registry=registry,
            )
            with self.subTest(schema=name, mutation='positive'):
                self.assertEqual([], list(validator.iter_errors(example)))
            for field in schemas[name]['required']:
                mutated = copy.deepcopy(example)
                mutated.pop(field)
                with self.subTest(schema=name, mutation=f'missing-{field}'):
                    errors = list(validator.iter_errors(mutated))
                    self.assertTrue(
                        any(error.validator == 'required' for error in errors),
                        errors,
                    )
            mutated = copy.deepcopy(example)
            mutated['unexpected_contract_owner'] = True
            with self.subTest(schema=name, mutation='extra-owner'):
                errors = list(validator.iter_errors(mutated))
                self.assertTrue(
                    any(error.validator == 'additionalProperties' for error in errors),
                    errors,
                )

            def resolve(current_schema: dict, current_name: str) -> tuple[dict, str]:
                seen: set[tuple[str, str]] = set()
                while '$ref' in current_schema:
                    reference = current_schema['$ref']
                    marker = (current_name, reference)
                    self.assertNotIn(marker, seen)
                    seen.add(marker)
                    relative, _, fragment = reference.partition('#')
                    if relative:
                        target_uri = urljoin(schemas[current_name]['$id'], relative)
                        target_name = Path(urlsplit(target_uri).path).name
                    else:
                        target_name = current_name
                    current_schema = schemas[target_name]
                    current_name = target_name
                    if fragment:
                        self.assertTrue(fragment.startswith('/'))
                        for raw_token in fragment[1:].split('/'):
                            token = unquote(raw_token).replace('~1', '/').replace('~0', '~')
                            current_schema = current_schema[token]
                return current_schema, current_name

            required_paths: set[tuple[object, ...]] = set()

            def branch_valid(branch: dict, owner_name: str, value: object) -> bool:
                owner_validator = jsonschema.Draft202012Validator(
                    schemas[owner_name],
                    registry=registry,
                )
                return owner_validator.evolve(schema=branch).is_valid(value)

            def collect(
                current_schema: dict,
                current_name: str,
                value: object,
                path: tuple[object, ...],
            ) -> None:
                current_schema, current_name = resolve(current_schema, current_name)
                for keyword in ('oneOf', 'anyOf'):
                    if keyword in current_schema:
                        matches = [
                            branch
                            for branch in current_schema[keyword]
                            if branch_valid(branch, current_name, value)
                        ]
                        self.assertTrue(matches, (name, path, keyword))
                        collect(matches[0], current_name, value, path)
                        return
                if isinstance(value, dict):
                    for required in current_schema.get('required', []):
                        if required in value:
                            required_paths.add(path + (required,))
                    for field, child in value.items():
                        child_schema = current_schema.get('properties', {}).get(field)
                        if isinstance(child_schema, dict):
                            collect(child_schema, current_name, child, path + (field,))
                elif isinstance(value, list) and value:
                    item_schema = current_schema.get('items')
                    if isinstance(item_schema, dict):
                        collect(item_schema, current_name, value[0], path + (0,))

            collect(schemas[name], name, example, ())
            for path in sorted(required_paths, key=lambda item: tuple(map(str, item))):
                mutated = copy.deepcopy(example)
                parent = mutated
                for component in path[:-1]:
                    parent = parent[component]
                parent.pop(path[-1])
                with self.subTest(schema=name, mutation='missing-' + '/'.join(map(str, path))):
                    self.assertFalse(validator.is_valid(mutated))

        receipt_refs = set()
        stack = [schemas['receipt-v4.schema.json']]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                if '$ref' in value:
                    receipt_refs.add(value['$ref'])
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
        for owner in (
            'host_request', 'host_event', 'host_result', 'checkpoint',
            'protocol_error', 'principal', 'handoff',
            'authorization_decision', 'action_trace',
        ):
            self.assertIn(
                f'host-manifest-v1.schema.json#/$defs/{owner}',
                receipt_refs,
            )

    def test_stdlib_schema_loader_matches_positive_and_required_mutation_fixtures(self) -> None:
        validator = load_validator_module()
        registry = validator.load_v5_schema_registry()
        examples = make_v5_schema_examples()
        self.assertEqual(set(registry), set(examples))
        for name, example in examples.items():
            with self.subTest(schema=name, mutation='positive'):
                self.assertEqual(
                    [], validator.validate_v5_schema(example, name, registry),
                )
            mutated = copy.deepcopy(example)
            missing = registry[name]['required'][0]
            mutated.pop(missing)
            errors = validator.validate_v5_schema(mutated, name, registry)
            with self.subTest(schema=name, mutation=f'missing-{missing}'):
                self.assertTrue(
                    any(error['code'] == 'schema.required' for error in errors),
                    errors,
                )

    def test_validator_cli_accepts_public_l0_smoke(self) -> None:
        result = self.run_cmd(
            'scripts/validate_eval_suite.py', 'contract',
            'templates/eval-spec.l0.example.json',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_l1_l2_templates_are_schema_valid_nonready_contracts(self) -> None:
        fixtures = (
            (
                'templates/eval-spec.l1.example.json',
                'templates/scenarios.l1.example.jsonl',
                {'non_ready.verifier', 'non_ready.execution'},
            ),
            (
                'templates/eval-spec.example.json',
                'templates/scenarios.example.jsonl',
                {
                    'non_ready.verifier',
                    'non_ready.quality',
                    'non_ready.execution',
                },
            ),
        )
        for spec, scenarios, warning_codes in fixtures:
            with self.subTest(spec=spec):
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py',
                    'contract',
                    spec,
                    scenarios,
                    'templates/host-manifest.example.json',
                    '--json',
                    '-',
                )
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr,
                )
                report = json.loads(result.stdout)
                self.assertTrue(report['schema_valid'])
                self.assertFalse(report['execution_ready'])
                self.assertEqual([], report['errors'])
                self.assertEqual(
                    warning_codes,
                    {warning['code'] for warning in report['warnings']},
                )
                self.assertTrue(
                    all(
                        warning['family'] == 'readiness'
                        for warning in report['warnings']
                    ),
                )
        for removed in (
            'cases.example.jsonl',
            'cases.l1.example.jsonl',
            'holdout-cases.example.jsonl',
        ):
            self.assertFalse((ROOT / 'templates' / removed).exists())

    def test_validator_cli_rejects_removed_positional_protocol(self) -> None:
        result = self.run_cmd(
            'scripts/validate_eval_suite.py', 'templates/eval-spec.l0.example.json',
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('invalid choice', result.stderr)

    def test_validator_cli_rejects_v4_schema_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec = make_minimal_spec('L0')
            path = Path(tmp) / 'v4-spec.json'
            path.write_text(json.dumps(spec), encoding='utf-8')
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract', str(path),
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('schema.const', result.stdout)

    def test_v5_contract_accepts_materialized_execution_ready_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_contract_fixture(Path(tmp))
            result = self.run_cmd(
                'scripts/validate_eval_suite.py',
                'contract',
                str(paths['spec']),
                str(paths['scenarios']),
                str(paths['host']),
                '--json',
                '-',
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['schema_valid'])
        self.assertTrue(report['execution_ready'])
        self.assertEqual([], report['errors'])
        self.assertEqual([], report['warnings'])

    def test_v5_contract_readiness_and_strict_exit_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_contract_fixture(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['execution']['ready'] = False
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )
            normal = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
            strict = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-', '--strict',
            )
        self.assertEqual(normal.returncode, 0, normal.stdout + normal.stderr)
        report = json.loads(normal.stdout)
        self.assertTrue(report['schema_valid'])
        self.assertFalse(report['execution_ready'])
        self.assertEqual(
            ['non_ready.execution'],
            [warning['code'] for warning in report['warnings']],
        )
        self.assertEqual(strict.returncode, 1, strict.stdout + strict.stderr)

    def test_v5_contract_exact_owner_and_authority_mutations_fail_closed(self) -> None:
        mutations = {
            'legacy-ready': (
                lambda spec: spec.__setitem__('ready_for_scored_run', True),
                'schema.additionalProperties',
            ),
            'legacy-public-cases': (
                lambda spec: spec['suite'].__setitem__(
                    'public_cases', spec['suite'].pop('public_scenarios'),
                ),
                'schema.required',
            ),
            'module-shape': (
                lambda spec: spec['applicability'][0].__setitem__(
                    'status', 'not_applicable',
                ),
                'applicability.shape_mismatch',
            ),
            'execute-authority': (
                lambda spec: spec['authority']['runner_capabilities'].clear(),
                'authority.missing_execute',
            ),
        }
        for name, (mutate, expected_code) in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_v5_contract_fixture(Path(tmp))
                spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
                mutate(spec)
                paths['spec'].write_text(
                    json.dumps(spec, indent=2) + '\n', encoding='utf-8',
                )
                if name == 'module-shape':
                    rebind_v5_contract_fixture(paths)
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'contract',
                    str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                    '--json', '-',
                )
                self.assertEqual(
                    result.returncode, 1, result.stdout + result.stderr,
                )
                report = json.loads(result.stdout)
                self.assertIn(
                    expected_code,
                    {error['code'] for error in report['errors']},
                    report,
                )

    def test_l3_l4_and_high_risk_authority_require_explicit_bindings(self) -> None:
        fixtures = (
            ('L3', {'holdout.required', 'authority.manual_required', 'level.gates'}),
            (
                'L4',
                {
                    'holdout.required',
                    'authority.manual_required',
                    'level.gates',
                    'treatment.prior_required',
                },
            ),
            ('high-risk', {'authority.manual_required'}),
        )
        for case, expected_codes in fixtures:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_v5_contract_fixture(Path(tmp))
                spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
                if case in {'L3', 'L4'}:
                    spec['level'] = case
                else:
                    spec['risk_tier'] = 'high'
                paths['spec'].write_text(
                    json.dumps(spec, indent=2) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'contract',
                    str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                    '--json', '-',
                )
                self.assertEqual(
                    result.returncode, 1, result.stdout + result.stderr,
                )
                report = json.loads(result.stdout)
                self.assertTrue(
                    expected_codes <= {
                        error['code'] for error in report['errors']
                    },
                    report,
                )

    def test_l4_prior_treatment_must_match_candidate_mode_and_estimand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_contract_fixture(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['level'] = 'L4'
            for decision in spec['applicability']:
                if decision['module'] == 'longitudinal':
                    decision['status'] = 'required'
                    decision['reason'] = 'L4 compares immutable cycles'
            prior = copy.deepcopy(spec['treatments'][1])
            prior.update({
                'treatment_id': 'prior',
                'profile': 'prior/natural_routing',
                'causal_role': 'prior',
                'implementation_hash': 'sha256:' + '9' * 64,
            })
            spec['treatments'].append(prior)
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(
            {'treatment.prior_mode', 'treatment.prior_estimand'} <= {
                error['code'] for error in report['errors']
            },
            report,
        )

    def test_l3_l4_holdout_preparation_and_revealed_execution(self) -> None:
        for level, exposure in (
            ('L3', 'sealed'),
            ('L3', 'exposed'),
            ('L4', 'sealed'),
        ):
            with (
                self.subTest(level=level, exposure=exposure),
                tempfile.TemporaryDirectory() as tmp,
            ):
                paths = materialize_v5_contract_fixture(Path(tmp))
                root = Path(tmp)
                public_scenario = json.loads(
                    paths['scenarios'].read_text(encoding='utf-8'),
                )
                heldout_scenario = {
                    **copy.deepcopy(public_scenario),
                    'case_id': 'heldout-case',
                    'split': 'heldout',
                }
                heldout_scenario['execution_context']['task'] = (
                    'Exercise the separately heldout contract boundary.'
                )
                heldout_scenario['turns'][0]['input']['content'] = (
                    'Exercise the separately heldout contract boundary.'
                )
                heldout_scenario['tags'] = [
                    *heldout_scenario['tags'],
                    'heldout-boundary',
                ]
                payload = root / 'holdout-scenarios.jsonl'
                payload.write_text(
                    json.dumps(heldout_scenario, separators=(',', ':')) + '\n',
                    encoding='utf-8',
                )
                payload_hash = (
                    'sha256:' + hashlib.sha256(payload.read_bytes()).hexdigest()
                )
                manifest = root / 'holdout-manifest.json'
                manifest.write_text(
                    json.dumps({
                        'schema_version': 1,
                        'payload_file': payload.name,
                        'payload_sha256': payload_hash,
                        'scenario_count': 1,
                        'scenarios': [{
                            'case_id': 'heldout-case',
                            'scenario_sha256': 'sha256:' + '8' * 64,
                            'risk': 'standard',
                            'tags': ['heldout'],
                        }],
                        'scenario_ids': ['heldout-case'],
                        'custodian': 'independent-evaluation-owner',
                        'exposure_status': exposure,
                    }, indent=2) + '\n',
                    encoding='utf-8',
                )
                spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
                spec['level'] = level
                spec['execution']['ready'] = exposure == 'exposed'
                spec['suite']['holdout'] = {
                    'manifest': {
                        'path': manifest.name,
                        'sha256': (
                            'sha256:'
                            + hashlib.sha256(manifest.read_bytes()).hexdigest()
                        ),
                    },
                    'payload': {
                        'path': payload.name,
                        'sha256': payload_hash,
                    },
                    'custodian': 'independent-evaluation-owner',
                    'exposure_status': exposure,
                }
                if exposure == 'exposed':
                    execution = root / 'execution-scenarios.jsonl'
                    execution.write_text(
                        ''.join(
                            json.dumps(item, separators=(',', ':')) + '\n'
                            for item in (public_scenario, heldout_scenario)
                        ),
                        encoding='utf-8',
                    )
                    spec['suite']['scenarios'] = {
                        'path': execution.name,
                        'sha256': (
                            'sha256:'
                            + hashlib.sha256(execution.read_bytes()).hexdigest()
                        ),
                    }
                    paths['scenarios'] = execution
                spec['authority']['manual_review'] = {
                    'required': True,
                    'role': 'release-reviewer',
                    'decision_contract_hash': 'sha256:' + '7' * 64,
                }
                for kind in ('safety', 'host', 'manual'):
                    spec['hard_gates'].append({
                        'gate_id': f'{kind}-gate',
                        'kind': kind,
                        'metric': f'{kind}_closed',
                        'direction': 'equal',
                        'threshold': True,
                        'authority': 'evaluation-owner',
                        'required': True,
                    })
                if level == 'L4':
                    for decision in spec['applicability']:
                        if decision['module'] == 'longitudinal':
                            decision['status'] = 'required'
                            decision['reason'] = 'immutable cycle comparison'
                    prior = copy.deepcopy(spec['treatments'][1])
                    prior.update({
                        'treatment_id': 'prior',
                        'profile': 'prior/force_loaded',
                        'causal_role': 'prior',
                        'implementation_hash': 'sha256:' + '9' * 64,
                    })
                    prior['expected_capabilities'].append('clock_capture')
                    spec['treatments'].append(prior)
                    spec['host']['required_capabilities'].append('clock_capture')
                    for treatment in spec['treatments'][:2]:
                        treatment['expected_capabilities'].append('clock_capture')
                    spec['analysis']['estimands'].append({
                        'estimand_id': 'cycle-change',
                        'metric': 'task_pass_rate',
                        'candidate_treatment_id': 'candidate',
                        'comparator_treatment_id': 'prior',
                        'direction': 'higher_is_better',
                        'effect': 'absolute',
                        'minimum_benefit': 0.0,
                        'eligible_modules': ['longitudinal'],
                    })
                    host = json.loads(
                        paths['host'].read_text(encoding='utf-8'),
                    )
                    probe = copy.deepcopy(host['capabilities'][0])
                    probe['capability'] = 'clock_capture'
                    host['capabilities'].append(probe)
                    paths['host'].write_text(
                        json.dumps(host, indent=2) + '\n',
                        encoding='utf-8',
                    )
                    scenario = json.loads(
                        paths['scenarios'].read_text(encoding='utf-8'),
                    )
                    scenario['applicable_treatment_profiles'].append(
                        'prior/force_loaded',
                    )
                    paths['scenarios'].write_text(
                        json.dumps(scenario, separators=(',', ':')) + '\n',
                        encoding='utf-8',
                    )
                paths['spec'].write_text(
                    json.dumps(spec, indent=2) + '\n',
                    encoding='utf-8',
                )
                proof = json.loads(
                    paths['quality_proof'].read_text(encoding='utf-8'),
                )
                proof['custody'].update({
                    'custodian': 'independent-evaluation-owner',
                    'exposure_status': exposure,
                })
                if exposure == 'exposed':
                    proof['case_classes'].append({
                        'case_id': heldout_scenario['case_id'],
                        'class': 'positive',
                    })
                    proof['golden']['case_ids'].append(
                        heldout_scenario['case_id'],
                    )
                    proof['golden']['passed_ids'].append(
                        heldout_scenario['case_id'],
                    )
                    proof['provenance_clusters'][0]['case_ids'].append(
                        heldout_scenario['case_id'],
                    )
                    validator = load_validator_module()
                    proof['duplicate_groups'] = [
                        {
                            'group_id': f'{kind}-{index}',
                            'kind': kind,
                            'case_ids': sorted(group),
                            'status': 'allowed',
                            'review_locator': None,
                        }
                        for kind in (
                            'exact',
                            'prompt_overlap',
                            'fixture_overlap',
                        )
                        for index, group in enumerate(
                            validator._derive_duplicate_groups(
                                [public_scenario, heldout_scenario],
                                kind,
                            ),
                            start=1,
                        )
                    ]
                proof['custody']['split_hashes']['heldout'] = payload_hash
                paths['quality_proof'].write_text(
                    json.dumps(proof, indent=2) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'contract',
                    str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                    '--json', '-',
                )
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr,
                )

    def test_probe_status_has_exact_nonexecute_or_execute_disposition(self) -> None:
        validator = load_validator_module()
        for status, expected in {
            'unsupported': ('unsupported', 'unsupported'),
            'unknown': ('not_evaluable', 'not_evaluable'),
            'pass': ('execute', 'feasible'),
        }.items():
            host = make_v5_schema_examples()['host-manifest-v1.schema.json']
            host['capabilities'][0]['probe']['status'] = status
            with self.subTest(status=status):
                self.assertEqual(
                    expected,
                    validator.derive_entry_disposition({'force_load'}, host),
                )
        with self.assertRaisesRegex(ValueError, 'probe is missing'):
            validator.derive_entry_disposition(
                {'model_grading'},
                make_v5_schema_examples()['host-manifest-v1.schema.json'],
            )

    def test_host_protocol_records_enforce_self_hash_and_terminal_result(self) -> None:
        validator = load_validator_module()
        receipt = make_v5_schema_examples()['receipt-v4.schema.json']
        request = receipt['host_protocol']['requests'][0]
        result = receipt['host_protocol']['results'][0]

        self.assertEqual(
            [], validator.validate_host_protocol_record('host_request', request),
        )
        tampered = copy.deepcopy(request)
        tampered['payload']['case_id'] = 'case-tampered'
        self.assertEqual(
            {'host_protocol.request_hash'},
            {
                error['code']
                for error in validator.validate_host_protocol_record(
                    'host_request', tampered,
                )
            },
        )
        self.assertEqual(
            [], validator.validate_host_protocol_record('host_result', result),
        )
        nonterminal = copy.deepcopy(result)
        nonterminal['terminal'] = False
        self.assertEqual(
            {'schema.const'},
            {
                error['code']
                for error in validator.validate_host_protocol_record(
                    'host_result', nonterminal,
                )
            },
        )

    def test_cross_contract_semantic_mutations_have_exact_codes(self) -> None:
        def mutate_treatment(paths: dict[str, Path]) -> None:
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['treatments'][1]['model_identity'] = 'sha256:' + '9' * 64
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )

        def mutate_requirement(paths: dict[str, Path]) -> None:
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['requirements'][0]['owner'] = 'model'
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )

        def mutate_fault(paths: dict[str, Path]) -> None:
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['turns'][0]['activate_faults'] = ['missing-fault']
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )

        def mutate_host_probe(paths: dict[str, Path]) -> None:
            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            host['capabilities'][0]['capability'] = 'natural_routing'
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n', encoding='utf-8',
            )

        def mutate_coordination(paths: dict[str, Path]) -> None:
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['subject']['shape'] = 'handoff_graph'
            spec['subject']['principal_mode'] = 'multiple'
            spec['subject']['mechanisms'].extend([
                'stateful', 'composition_orchestration',
            ])
            required = {
                'declared_composition',
                'multi_principal_coordination',
                'multi_turn_state',
            }
            for decision in spec['applicability']:
                if decision['module'] in required:
                    decision['status'] = 'required'
                    decision['reason'] = 'required by handoff graph fixture'
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )

        def mutate_l3_holdout(paths: dict[str, Path]) -> None:
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['level'] = 'L3'
            spec['execution']['ready'] = False
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )

        mutations = (
            (mutate_treatment, 'treatment.execution_identity'),
            (mutate_requirement, 'requirement.owner_mismatch'),
            (mutate_fault, 'fault.unknown_activation'),
            (mutate_host_probe, 'host.probe_missing'),
            (mutate_coordination, 'coordination.required'),
            (mutate_l3_holdout, 'holdout.required'),
        )
        for mutate, expected_code in mutations:
            with self.subTest(code=expected_code), tempfile.TemporaryDirectory() as tmp:
                paths = materialize_v5_contract_fixture(Path(tmp))
                mutate(paths)
                rebind_v5_contract_fixture(paths)
                result = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'contract',
                    str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                    '--json', '-',
                )
                self.assertEqual(
                    result.returncode, 1, result.stdout + result.stderr,
                )
                report = json.loads(result.stdout)
                self.assertIn(
                    expected_code,
                    {error['code'] for error in report['errors']},
                    report,
                )

    def test_required_multi_turn_module_requires_two_actual_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_stateful_fixture(Path(tmp))
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['turns'] = scenario['turns'][:1]
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)

            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
            self.assertEqual(
                result.returncode, 1, result.stdout + result.stderr,
            )
            report = json.loads(result.stdout)
            self.assertIn(
                'state.multi_turn_required',
                {error['code'] for error in report['errors']},
            )

    def test_observation_contract_separates_bytes_temporality_and_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_contract_fixture(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['graders'][0]['checks'].append({
                'check_id': 'grounding-check',
                'dimension': 'grounding',
                'required': True,
                'pass_condition': 'The claim is supported by fresh source evidence.',
            })
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n', encoding='utf-8',
            )
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['requirements'].append({
                'requirement_id': 'grounding',
                'dimension': 'grounding',
                'required': True,
                'owner': 'deterministic',
                'grader_id': 'fixture-grader',
                'check_id': 'grounding-check',
                'checkpoint': 'final',
                'obligation': None,
                'transition_id': None,
                'safety_severity': None,
                'safety_kind': None,
            })
            scenario['observation_contracts'] = [{
                'observation_id': 'source-observation',
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
                'expected_hash': 'sha256:' + hashlib.sha256(
                    paths['host'].read_bytes(),
                ).hexdigest(),
                'predicate': None,
                'valid_from_seq': 0,
                'valid_until_seq': 1,
                'valid_from_utc': None,
                'valid_until_utc': None,
                'freshness_requirement': 'captured during the attempt',
                'clock_requirement': 'monotonic sequence',
                'consumer_requirement_ids': ['grounding'],
            }]
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            valid = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['observation_contracts'][0]['predicate'] = 'must match'
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            invalid = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertEqual(invalid.returncode, 1, invalid.stdout + invalid.stderr)
        self.assertIn(
            'observation.bytes_contract',
            {error['code'] for error in json.loads(invalid.stdout)['errors']},
        )

    def test_handoff_graph_closes_slots_dependencies_state_and_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_handoff_fixture(Path(tmp))
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']), str(paths['scenarios']), str(paths['host']),
                '--json', '-',
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_routing_and_composition_contracts_are_exact_and_conditional(
        self,
    ) -> None:
        for materialize in (
            materialize_v5_routing_fixture,
            materialize_v5_composition_fixture,
        ):
            with (
                self.subTest(materialize=materialize.__name__),
                tempfile.TemporaryDirectory() as tmp,
            ):
                paths = materialize(Path(tmp))
                valid = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'contract',
                    str(paths['spec']), str(paths['scenarios']),
                    str(paths['host']), '--json', '-',
                )
                self.assertEqual(
                    valid.returncode, 0, valid.stdout + valid.stderr,
                )
                scenario = json.loads(
                    paths['scenarios'].read_text(encoding='utf-8'),
                )
                scenario['routing_contract']['expectations'].pop()
                paths['scenarios'].write_text(
                    json.dumps(scenario, separators=(',', ':')) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                invalid = self.run_cmd(
                    'scripts/validate_eval_suite.py', 'contract',
                    str(paths['spec']), str(paths['scenarios']),
                    str(paths['host']), '--json', '-',
                )
                self.assertEqual(
                    invalid.returncode, 1,
                    invalid.stdout + invalid.stderr,
                )
                self.assertIn(
                    'routing.expectation_matrix',
                    {
                        item['code']
                        for item in json.loads(invalid.stdout)['errors']
                    },
                )

if __name__ == '__main__':
    unittest.main()  # noqa: F405
