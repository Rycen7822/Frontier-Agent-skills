from __future__ import annotations

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
        self.assertEqual(2, complete["eligible_case_count"])

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
        self.assertEqual(1, incomplete["eligible_case_count"])

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


    def test_primary_benefit_contract_is_finite_and_replaces_legacy_gate_id(self) -> None:
        analyzer = load_analyzer_module()
        spec = make_minimal_spec('L2')
        spec['analysis']['primary_benefit'] = {
            'metric': 'task_pass_rate',
            'comparator': 'baseline',
            'direction': 'higher_is_better',
            'effect': 'absolute',
            'minimum_benefit': 0.0,
        }
        spec['metrics'] = ['task_pass_rate']
        spec['hard_gates'] = [{
            'id': 'protected-outcomes', 'metric': 'protected_outcome_failures',
            'operator': '==', 'value': 0,
        }]
        errors: list[str] = []
        analyzer.check_spec(spec, errors, [])
        self.assertEqual([], errors)

        for field, value in (
            ('metric', 'free-form-metric'),
            ('comparator', 'candidate'),
            ('direction', 'smaller'),
            ('effect', 'ratio'),
            ('minimum_benefit', -0.01),
        ):
            with self.subTest(field=field):
                mutated = copy.deepcopy(spec)
                mutated['analysis']['primary_benefit'][field] = value
                errors = []
                analyzer.check_spec(mutated, errors, [])
                self.assertTrue(any(f'primary_benefit.{field}' in error for error in errors), errors)

        legacy = copy.deepcopy(spec)
        legacy['analysis']['usefulness_benefit_gate_id'] = 'legacy-benefit'
        errors = []
        analyzer.check_spec(legacy, errors, [])
        self.assertTrue(any('usefulness_benefit_gate_id' in error for error in errors), errors)


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
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            first = add_context_component(
                bundle, artifact_name='body-1.txt', content='same static bytes\n',
            )
            repeated = add_context_component(
                bundle, artifact_name='body-2.txt', content='same static bytes\n', append=True,
            )
            protocol = add_context_component(
                bundle, kind='protocol_output', source_path='protocol:helper:1',
                artifact_name='protocol.txt', content='protocol bytes\n', append=True,
            )
            failed = add_context_component(
                bundle, kind='failed_command_output', source_path='failed-command:helper:1',
                artifact_name='failed.txt', content='failed bytes\n', append=True,
            )
            first_reference = add_context_component(
                bundle, kind='reference', source_path='references/release.md',
                artifact_name='reference-1.txt', content='same reference bytes\n',
                append=True,
            )
            repeated_reference = add_context_component(
                bundle, kind='reference', source_path='references/release.md',
                artifact_name='reference-2.txt', content='same reference bytes\n',
                append=True,
            )
            report = self.assert_valid_receipt_bundle(bundle)
            context = report['run_matrix'][0]['context_usage']
            self.assertEqual(
                context['unique_static_content_bytes'],
                len(first.read_bytes()) + len(first_reference.read_bytes()),
            )
            self.assertEqual(
                context['repeated_static_content_bytes'],
                len(repeated.read_bytes()) + len(repeated_reference.read_bytes()),
            )
            self.assertEqual(context['protocol_output_bytes'], len(protocol.read_bytes()))
            self.assertEqual(context['failed_command_output_bytes'], len(failed.read_bytes()))
            self.assertEqual(context['host_integration_duplicate_bytes'], len(repeated.read_bytes()))
            self.assertEqual(
                context['unexplained_repeated_static_content_bytes'],
                len(repeated_reference.read_bytes()),
            )
            self.assertEqual(context['unattributed_model_body_read_count'], 0)
            self.assertEqual(
                context['controlled_bytes'],
                context['bytes'] - context['host_integration_duplicate_bytes'],
            )
            self.assertEqual(
                context['unique_reference_bytes'],
                len(first_reference.read_bytes()),
            )
            self.assertEqual(
                context['controlled_core_bytes'],
                context['controlled_bytes'] - len(first_reference.read_bytes()),
            )
            self.assertEqual(
                context['bytes'],
                sum(context[field] for field in (
                    'unique_static_content_bytes', 'repeated_static_content_bytes',
                    'protocol_output_bytes', 'failed_command_output_bytes',
                )),
            )
            self.assertEqual(
                {
                    'unique_static_content_bytes', 'repeated_static_content_bytes',
                    'protocol_output_bytes', 'failed_command_output_bytes',
                    'host_integration_duplicate_bytes',
                    'unexplained_repeated_static_content_bytes',
                },
                set(report['context_efficiency']),
            )
            self.assertTrue(all(set(value) == {'p50', 'p95', 'max'} for value in report['context_efficiency'].values()))
            self.assertIn('controlled_skill_context_bytes_p95', report['skill_context'])

            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            next(
                item for item in receipt['context_usage']['components']
                if item['kind'] == 'protocol_output'
            )['source_path'] = 'failed-command:helper:2'
            rewrite_bound_receipt(bundle, receipt)
            invalid = self.run_receipt_analysis(bundle)
            self.assertEqual(3, invalid.returncode, invalid.stdout + invalid.stderr)
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
            'early candidate failure': [
                row('candidate', 'case-a', 10, task_pass=False), candidate_rows[1], *prior_rows,
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
            bundle = write_receipt_bundle(Path(tmp))
            stdout_path = bundle['artifact_dir'] / 'verifier/stdout.json'
            output = json.loads(stdout_path.read_text(encoding='utf-8'))
            output['overall_pass'] = False
            output['score'] = 0
            output['checks'][0]['pass'] = False
            stdout_path.write_text(json.dumps(output, separators=(',', ':')) + '\n', encoding='utf-8')
            receipt = json.loads(bundle['receipt'].read_text(encoding='utf-8'))
            stdout_hash = 'sha256:' + hashlib.sha256(stdout_path.read_bytes()).hexdigest()
            next(item for item in receipt['artifacts'] if item['path'] == 'verifier/stdout.json')['sha256'] = stdout_hash
            receipt['grader_outputs'][0]['invocation']['exit_code'] = 1
            rewrite_bound_receipt(bundle, receipt)
            result = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']), '--spec', str(bundle['spec']),
                '--json', str(bundle['summary']),
            )
            summary = json.loads(bundle['summary'].read_text(encoding='utf-8'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(summary['evidence_status'], 'complete')
        self.assertEqual(summary['usefulness_status'], 'not_evaluable')
        self.assertFalse(summary['run_matrix'][0]['task_pass'])


    def test_analyzer_json_stdout_is_not_polluted_by_human_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = write_receipt_bundle(Path(tmp))
            markdown_path = Path(tmp) / 'summary.md'
            result = self.call_cli(
                'scripts/analyze_runs.py', str(bundle['index']),
                '--spec', str(bundle['spec']), '--json', '-', '--markdown', str(markdown_path), '--report-only',
            )
            markdown = markdown_path.read_text(encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['record_count'], 1)
        self.assertEqual(report['evidence_status'], 'complete')
        decision = (
            'evidence_status=complete usefulness_status=not_evaluable '
            'final_authority_status=blocked decision_signal=diagnostic_complete'
        )
        self.assertEqual(
            decision,
            ' '.join(f'{key}={report[key]}' for key in (
                'evidence_status', 'usefulness_status', 'final_authority_status', 'decision_signal',
            )),
        )
        self.assertNotIn('Analyzed', result.stdout)
        self.assertIn('Analyzed 1 records', result.stderr)
        self.assertIn(f'Decision status: {decision}', result.stderr)
        self.assertIn(f'Decision status: `{decision}`', markdown)

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
