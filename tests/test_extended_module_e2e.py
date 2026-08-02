from __future__ import annotations

from skill_evaluator_test_support import *  # noqa: F403


class TestExtendedModuleE2E(SkillEvaluatorTestCase):  # noqa: F405
    def _run_campaign(
        self,
        root: Path,
        materialize,
        *,
        mode: str | None = None,
        expected_runner_exit: int = 0,
    ) -> dict:
        paths = materialize(root)
        if mode is not None:
            set_v5_synthetic_host_mode(paths, mode)
        plan_path = root / 'execution-plan.json'
        compiled = self.run_cmd(
            'scripts/compile_eval_plan.py',
            str(paths['spec']),
            str(paths['scenarios']),
            str(paths['host']),
            '--output', str(plan_path),
        )
        self.assertEqual(
            compiled.returncode, 0, compiled.stdout + compiled.stderr,
        )
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        index_path = (
            root / plan['artifacts']['root']
            / plan['artifacts']['index_relpath']
        )
        executed = self.run_cmd(
            'scripts/run_eval_plan.py',
            str(plan_path),
            '--index', str(index_path),
            '--new-attempt-budget', str(
                runner_worst_case_attempt_budget(plan)
            ),
        )
        self.assertEqual(
            expected_runner_exit,
            executed.returncode,
            executed.stdout + executed.stderr,
        )
        if expected_runner_exit != 0:
            self.assertFalse(index_path.exists())
            return {'plan': plan, 'runner': executed}

        summary_path = root / 'summary.json'
        failures_path = root / 'failures.json'
        analyzed = self.run_cmd(
            'scripts/analyze_runs.py',
            str(index_path),
            '--spec', str(paths['spec']),
            '--json', str(summary_path),
            '--failure-index', str(failures_path),
        )
        self.assertIn(
            analyzed.returncode, {0, 1, 3},
            analyzed.stdout + analyzed.stderr,
        )
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        failures = json.loads(failures_path.read_text(encoding='utf-8'))
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
        return {
            'paths': paths,
            'plan': plan,
            'index': index_path,
            'summary': summary,
            'failures': failures,
        }

    def test_seven_minimal_plans_close_required_and_inactive_modules(
        self,
    ) -> None:
        campaigns = (
            (
                'compact',
                materialize_v5_contract_fixture,
                {'core_outcome'},
            ),
            (
                'crowded-catalog',
                materialize_v5_routing_fixture,
                {'core_outcome', 'natural_routing', 'catalog_routing'},
            ),
            (
                'declared-composition',
                materialize_v5_composition_fixture,
                {
                    'core_outcome', 'declared_composition',
                    'multi_turn_state',
                },
            ),
            (
                'multi-principal-handoff',
                materialize_v5_fanout_critique_fixture,
                {
                    'core_outcome', 'declared_composition',
                    'multi_principal_coordination', 'multi_turn_state',
                },
            ),
            (
                'multi-turn-state',
                materialize_v5_interrupt_resume_fixture,
                {'core_outcome', 'multi_turn_state'},
            ),
            (
                'typed-fault',
                materialize_v5_fault_matrix_fixture,
                {'core_outcome', 'tool_faults'},
            ),
            (
                'dynamic-security-host',
                materialize_v5_security_fixture,
                {'core_outcome', 'host_conformance', 'dynamic_security'},
            ),
        )
        for name, materialize, required in campaigns:
            with (
                self.subTest(campaign=name),
                tempfile.TemporaryDirectory() as tmp,
            ):
                result = self._run_campaign(Path(tmp), materialize)
                summary = result['summary']
                self.assertTrue(summary['analysis_ready'])
                self.assertEqual('complete', summary['evidence_status'])
                self.assertEqual('feasible', summary['feasibility_status'])
                self.assertNotEqual(
                    'supported', summary['usefulness_status'],
                )
                modules = {
                    item['module']: item
                    for item in summary['module_summaries']
                }
                self.assertEqual(
                    required,
                    {
                        item['module']
                        for item in result['plan']['module_decisions']
                        if item['status'] == 'required'
                    },
                )
                for module, item in modules.items():
                    if module in required:
                        self.assertEqual('pass', item['status'])
                        self.assertGreater(item['present'], 0)
                    else:
                        self.assertEqual('not_applicable', item['status'])
                        self.assertEqual(0, item['planned'])
                        self.assertEqual(0, item['present'])
                self.assertEqual(2, result['plan']['expected_counts']['total'])
                for row in map(
                    json.loads,
                    result['index'].read_text(encoding='utf-8').splitlines(),
                ):
                    receipt = json.loads(
                        (
                            result['index'].parent
                            / row['receipt']['path']
                        ).read_text(encoding='utf-8'),
                    )
                    self.assertEqual(
                        ['probe_capability', 'execute_case'],
                        [
                            item['envelope']['request_kind']
                            for item in receipt['host_protocol']['requests']
                        ],
                    )
                if name == 'crowded-catalog':
                    routing_stages = [
                        item for item in summary['stage_summaries']
                        if item['surface'] == 'skill_tool_access'
                    ]
                    self.assertEqual(7, len(routing_stages))
                    self.assertEqual(
                        {'pass'},
                        {item['status'] for item in routing_stages},
                    )
                    self.assertEqual(
                        {8}, {item['eligible'] for item in routing_stages},
                    )

    def test_two_host_security_gates_remain_independent(self) -> None:
        results = {}
        for host_id, mode in (
            ('synthetic-host-a', None),
            ('synthetic-host-b', 'treatment-failure'),
        ):
            with (
                self.subTest(host_id=host_id),
                tempfile.TemporaryDirectory() as tmp,
            ):
                materialize = lambda root, host_id=host_id: (  # noqa: E731
                    materialize_v5_security_fixture(root, host_id=host_id)
                )
                results[host_id] = self._run_campaign(
                    Path(tmp), materialize, mode=mode,
                )
                logical = json.loads(
                    results[host_id]['paths']['scenarios'].read_text(
                        encoding='utf-8',
                    ),
                )
                logical['fixture']['sha256'] = '<bound-host>'
                for observation in logical['observation_contracts']:
                    observation['producer'] = '<bound-host>'
                results[host_id]['logical_scenario'] = logical
        host_a = {
            item['module']: item['status']
            for item in results['synthetic-host-a']['summary'][
                'module_summaries'
            ]
        }
        host_b = {
            item['module']: item['status']
            for item in results['synthetic-host-b']['summary'][
                'module_summaries'
            ]
        }
        self.assertEqual('pass', host_a['dynamic_security'])
        self.assertEqual('pass', host_a['host_conformance'])
        self.assertEqual('fail', host_b['dynamic_security'])
        self.assertEqual('fail', host_b['host_conformance'])
        self.assertNotEqual(
            results['synthetic-host-a']['plan']['host_manifest_hash'],
            results['synthetic-host-b']['plan']['host_manifest_hash'],
        )
        self.assertEqual(
            results['synthetic-host-a']['logical_scenario'],
            results['synthetic-host-b']['logical_scenario'],
        )
        self.assertNotEqual(
            'supported',
            results['synthetic-host-b']['summary']['usefulness_status'],
        )

    def test_declared_pair_and_sequence_keep_distinct_order_semantics(
        self,
    ) -> None:
        for mode in ('unordered_pair', 'ordered_sequence'):
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory() as tmp,
            ):
                materialize = lambda root, mode=mode: (  # noqa: E731
                    materialize_v5_composition_fixture(
                        root, composition_mode=mode,
                    )
                )
                result = self._run_campaign(Path(tmp), materialize)
                plan = result['plan']
                candidate = next(
                    item for item in plan['entries']
                    if item['treatment_id'] == 'candidate'
                )
                row = next(
                    json.loads(line)
                    for line in result['index'].read_text(
                        encoding='utf-8',
                    ).splitlines()
                    if json.loads(line)['entry_id'] == candidate['entry_id']
                )
                receipt = json.loads(
                    (
                        result['index'].parent
                        / row['receipt']['path']
                    ).read_text(encoding='utf-8'),
                )
                per_turn = [
                    event['payload']['routing']['composition']
                    for event in receipt['host_protocol']['events']
                ]
                if mode == 'unordered_pair':
                    self.assertNotEqual(per_turn[0], per_turn[1])
                    self.assertEqual(set(per_turn[0]), set(per_turn[1]))
                else:
                    self.assertEqual(per_turn[0], per_turn[1])
                module = next(
                    item for item in result['summary']['module_summaries']
                    if item['module'] == 'declared_composition'
                )
                self.assertEqual('pass', module['status'])

    def test_module_boundary_campaigns_fail_at_runtime_owner(self) -> None:
        campaigns = (
            (
                materialize_v5_routing_fixture,
                'routing-mismatch',
                2,
            ),
            (
                materialize_v5_composition_fixture,
                'routing-mismatch',
                2,
            ),
            (
                materialize_v5_fanout_critique_fixture,
                'partial-join-silent',
                2,
            ),
            (
                materialize_v5_fault_matrix_fixture,
                'fault-not-triggered',
                3,
            ),
            (
                materialize_v5_interrupt_resume_fixture,
                'state-obligation-mismatch',
                2,
            ),
            (
                materialize_v5_interrupt_resume_fixture,
                'state-cleanup-mismatch',
                2,
            ),
            (
                materialize_v5_security_fixture,
                'unauthorized-execution',
                2,
            ),
        )
        for materialize, mode, expected_exit in campaigns:
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory() as tmp,
            ):
                self._run_campaign(
                    Path(tmp),
                    materialize,
                    mode=mode,
                    expected_runner_exit=expected_exit,
                )

    def test_security_action_observation_and_capability_boundaries(
        self,
    ) -> None:
        for mode in ('allow-with-changes', 'deny'):
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory() as tmp,
            ):
                result = self._run_campaign(
                    Path(tmp), materialize_v5_security_fixture, mode=mode,
                )
                summary = result['summary']
                self.assertEqual('pass', summary['action_summary']['status'])
                self.assertEqual(
                    'pass', summary['grounding_summary']['status'],
                )
                self.assertEqual(
                    4, summary['grounding_summary']['metrics']['observations'],
                )
                self.assertNotEqual(
                    'supported', summary['usefulness_status'],
                )
                if mode == 'deny':
                    self.assertEqual(
                        2, summary['action_summary']['metrics']['denied'],
                    )
                    self.assertEqual(
                        2,
                        summary['action_summary']['metrics'][
                            'denied_without_execution'
                        ],
                    )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_security_fixture(root)
            scenario = json.loads(
                paths['scenarios'].read_text(encoding='utf-8'),
            )
            scenario['observation_contracts'][0]['valid_until_seq'] = 1
            paths['scenarios'].write_text(
                json.dumps(scenario, separators=(',', ':')) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            self._run_campaign(
                root,
                lambda _: paths,
                expected_runner_exit=3,
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = materialize_v5_security_fixture(root)
            host = json.loads(paths['host'].read_text(encoding='utf-8'))
            next(
                item for item in host['capabilities']
                if item['capability'] == 'action_authorization_trace'
            )['probe']['status'] = 'unsupported'
            paths['host'].write_text(
                json.dumps(host, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            plan_path = root / 'execution-plan.json'
            compiled = self.run_cmd(
                'scripts/compile_eval_plan.py',
                str(paths['spec']),
                str(paths['scenarios']),
                str(paths['host']),
                '--output', str(plan_path),
            )
            self.assertEqual(
                compiled.returncode, 0,
                compiled.stdout + compiled.stderr,
            )
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            self.assertEqual(0, plan['expected_counts']['execute'])
            self.assertEqual(2, plan['expected_counts']['unsupported'])

    def test_host_adapter_claim_must_equal_bound_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = materialize_v5_security_fixture(Path(tmp))
            spec = json.loads(paths['spec'].read_text(encoding='utf-8'))
            spec['subject']['claimed_hosts'] = ['synthetic-host-b']
            paths['spec'].write_text(
                json.dumps(spec, indent=2) + '\n',
                encoding='utf-8',
            )
            rebind_v5_contract_fixture(paths)
            result = self.run_cmd(
                'scripts/validate_eval_suite.py', 'contract',
                str(paths['spec']),
                str(paths['scenarios']),
                str(paths['host']),
                '--json', '-',
            )
            self.assertEqual(
                result.returncode, 1, result.stdout + result.stderr,
            )
            self.assertIn(
                'host.claim_binding',
                {
                    item['code']
                    for item in json.loads(result.stdout)['errors']
                },
            )

    def test_critique_consensus_and_cache_evidence_cannot_self_promote(
        self,
    ) -> None:
        for check_id in (
            'critique-uptake-check',
            'critique-repair-check',
        ):
            with (
                self.subTest(check_id=check_id),
                tempfile.TemporaryDirectory() as tmp,
            ):
                def materialize(root, check_id=check_id):
                    paths = materialize_v5_fanout_critique_fixture(root)
                    set_v5_grader_check_failure(paths, check_id)
                    return paths

                result = self._run_campaign(Path(tmp), materialize)
                self.assertEqual(
                    'fail', result['summary']['critique_summary']['status'],
                )
                self.assertEqual(
                    'not_supported',
                    result['summary']['usefulness_status'],
                )

        with tempfile.TemporaryDirectory() as tmp:
            def materialize_consensus(root):
                paths = materialize_v5_fanout_critique_fixture(root)
                scenario = json.loads(
                    paths['scenarios'].read_text(encoding='utf-8'),
                )
                scenario['coordination']['coordination_pattern'] = 'vote'
                scenario['coordination']['topology'] = 'decentralized'
                paths['scenarios'].write_text(
                    json.dumps(scenario, separators=(',', ':')) + '\n',
                    encoding='utf-8',
                )
                rebind_v5_contract_fixture(paths)
                return paths

            result = self._run_campaign(
                Path(tmp), materialize_consensus,
            )
            self.assertEqual(
                'not_evaluable',
                result['summary']['independence_summary']['status'],
            )
            self.assertNotEqual(
                'supported', result['summary']['usefulness_status'],
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_campaign(
                Path(tmp),
                materialize_v5_contract_fixture,
                mode='cache-hit',
            )
            self.assertEqual(
                10,
                result['summary']['context_cost']['cache']['metrics'][
                    'provider_cache_read_tokens'
                ],
            )
            self.assertNotEqual(
                'supported', result['summary']['usefulness_status'],
            )


if __name__ == '__main__':
    unittest.main()  # noqa: F405
